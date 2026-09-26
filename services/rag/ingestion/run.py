# ============================================
# services/rag/ingestion/run.py
# ============================================
"""
Terminal entry point for one-time ingestion.
Run via: python -m services.rag.ingestion.run --file data/UET_HR.pdf
"""

import argparse
import logging

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

from ..config import settings
from .chunker import index_to_qdrant, semantic_chunking
from .loader import load_pdf

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Execute the ingestion pipeline from terminal."""
    parser = argparse.ArgumentParser(description="Ingest documents into Qdrant")
    parser.add_argument("--file", type=str, required=True, help="Path to the PDF file")
    args = parser.parse_args()

    logger.info("Initializing embedding model...")
    embedder = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)

    logger.info(f"Connecting to Qdrant at {settings.QDRANT_URL} ...")
    client = QdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY,
        timeout=settings.QDRANT_TIMEOUT_SECONDS,
    )

    logger.info(f"Loading document: {args.file}")
    docs = load_pdf(args.file)
    full_text = "\n\n".join([doc.page_content for doc in docs])

    logger.info("Performing semantic chunking...")
    chunks = semantic_chunking(
        text=full_text,
        embedder=embedder,
        threshold=settings.CHUNK_SIMILARITY_THRESHOLD,
        source=args.file,
    )

    logger.info(f"Indexing {len(chunks)} chunks to Qdrant...")
    index_to_qdrant(
        docs=chunks,
        embedder=embedder,
        client=client,
        collection_name=settings.QDRANT_KB_COLLECTION,
        vector_size=settings.VECTOR_SIZE,
    )

    logger.info("Ingestion completed successfully.")


if __name__ == "__main__":
    main()

# uv run service/rag/ingestion/run.py
