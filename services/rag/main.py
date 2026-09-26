# ============================================
# services/rag/main.py
# ============================================
"""
Main FastAPI application for the RAG service.
"""

import logging
import threading
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env BEFORE any langchain/langsmith import so LANGSMITH_* and provider
# variables are present in os.environ for tracing clients.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException
from sentence_transformers import SentenceTransformer

from .api import router
from .config import settings
from .retrieval.cache import QdrantSemanticCache
from .retrieval.rerank import Reranker

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize models, clients, and retrievers."""
    logger.info("Loading embedding model...")
    app.state.embedder = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)

    # Reranker is LAZY-LOADED on first use (double-checked locking) so startup
    # stays fast and memory is only spent when reranking is actually needed.
    app.state.reranker = None
    app.state.reranker_lock = threading.Lock()

    logger.info("Connecting to Qdrant at %s ...", settings.QDRANT_URL)
    app.state.qdrant = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=settings.QDRANT_TIMEOUT_SECONDS,
    )

    logger.info("Initializing Semantic Cache...")
    app.state.semantic_cache = QdrantSemanticCache(
        client=app.state.qdrant,
        collection_name=settings.QDRANT_CACHE_COLLECTION,
        ttl_seconds=settings.CACHE_TTL_SECONDS,
        vector_size=settings.VECTOR_SIZE,
    )

    logger.info("Loading documents for BM25 index...")
    app.state.documents = _load_kb_documents(app.state.qdrant)

    logger.info("RAG service started successfully.")
    yield

    logger.info("Shutting down RAG service.")


def _load_kb_documents(qdrant: QdrantClient) -> list[Document]:
    """
    Load every KB chunk from Qdrant into LangChain Documents for the BM25 index.

    Args:
        qdrant: Connected Qdrant client.

    Returns:
        List of documents (empty when the KB collection does not exist yet).
    """
    documents: list[Document] = []
    if not qdrant.collection_exists(settings.QDRANT_KB_COLLECTION):
        return documents
    points = _scroll_kb_with_retry(qdrant)
    for point in points:
        payload = point.payload or {}
        documents.append(
            Document(page_content=payload.get("text", ""), metadata=payload)
        )
    return documents


def _scroll_kb_with_retry(qdrant: QdrantClient):
    """Load KB points with bounded retries for transient cloud timeouts."""
    attempts = max(1, settings.QDRANT_STARTUP_RETRIES)

    for attempt in range(1, attempts + 1):
        try:
            points, _ = qdrant.scroll(
                collection_name=settings.QDRANT_KB_COLLECTION,
                limit=10000,
                with_payload=True,
            )
            return points
        except ResponseHandlingException:
            if attempt == attempts:
                raise

            wait_seconds = attempt * 2
            logger.warning(
                "Qdrant KB scroll timed out (attempt %d/%d); retrying in %ds.",
                attempt,
                attempts,
                wait_seconds,
            )
            time.sleep(wait_seconds)

    return []


def get_reranker(app: FastAPI) -> Reranker:
    """
    Lazily build the cross-encoder reranker on first use (thread-safe).

    Uses double-checked locking: the fast path reads app.state.reranker
    without locking; only the first caller pays the model-load cost.

    Args:
        app: FastAPI application holding shared state.

    Returns:
        The shared Reranker instance.
    """
    if app.state.reranker is None:
        with app.state.reranker_lock:
            if app.state.reranker is None:
                logger.info(
                    "Lazy-loading reranker model %s ...", settings.RERANKER_MODEL_NAME
                )
                app.state.reranker = Reranker(settings.RERANKER_MODEL_NAME)
    return app.state.reranker


app = FastAPI(title="RAG Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/kb")


@app.get("/health")
def health() -> dict:
    """
    Liveness probe for infrastructure checks.

    Returns:
        Simple status payload.
    """
    return {"status": "ok"}
