# ============================================
# services/rag/api.py
# ============================================
"""
FastAPI endpoints for the RAG service.
"""

import logging
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Request
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from .config import settings
from .retrieval.hybrid import HybridRetriever
from .retrieval.hyde import HyDERetriever
from .retrieval.mmr import mmr_select

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query")
    top_k: int = Field(5, ge=1, le=20, description="Number of results")
    diversity: float = Field(0.7, ge=0.0, le=1.0, description="MMR lambda parameter")


class SearchResponse(BaseModel):
    results: list[dict[str, Any]] = Field(
        ..., description="List of chunks with metadata"
    )
    cache_hit: bool = Field(
        ..., description="Whether the result came from semantic cache"
    )


def get_services(request: Request) -> dict[str, Any]:
    """
    Dependency that returns shared service objects from app.state.

    Args:
        request: Incoming HTTP request carrying the application reference.

    Returns:
        Dict with embedder, qdrant, semantic_cache and documents.
        The reranker is intentionally NOT included: it is lazy-loaded inside
        the search endpoint via main.get_reranker (double-checked locking).
    """
    app = request.app
    return {
        "app": app,
        "embedder": app.state.embedder,
        "qdrant": app.state.qdrant,
        "semantic_cache": app.state.semantic_cache,
        "documents": app.state.documents,
    }


@router.post("/search", response_model=SearchResponse)
def search(
    request: SearchRequest, services: dict[str, Any] = Depends(get_services)
) -> SearchResponse:
    """
    Perform advanced retrieval:
    Cache Check -> Hybrid -> HyDE (if needed)
    -> Rerank (lazy-loaded) -> MMR -> cache write.

    Args:
        request: Query, top_k and diversity parameters.
        services: Shared objects resolved by get_services.

    Returns:
        SearchResponse with the final chunks and the cache_hit flag.
    """
    from .main import get_reranker

    query = request.query
    top_k = request.top_k
    diversity = request.diversity

    app = services["app"]
    embedder = services["embedder"]
    qdrant = services["qdrant"]
    semantic_cache = services["semantic_cache"]
    documents = services["documents"]

    # 1. Encode query
    query_vector = embedder.encode([query], normalize_embeddings=True)[0].tolist()

    # 2. Check Semantic Cache (TTL-aware)
    cached_answer = semantic_cache.get(
        query_vector, threshold=settings.CACHE_SIMILARITY_THRESHOLD
    )
    if cached_answer:
        logger.info("Semantic cache hit")
        return SearchResponse(
            results=[
                {"text": cached_answer, "source": "semantic_cache", "cache_hit": True}
            ],
            cache_hit=True,
        )

    # 3. Hybrid Retrieval (Dense + BM25 + RRF)
    hybrid_retriever = HybridRetriever(
        documents=documents,
        qdrant_client=qdrant,
        collection_name=settings.QDRANT_KB_COLLECTION,
    )

    def get_hybrid_docs(q: str) -> list[Document]:
        """Encode one query and run hybrid retrieval for it."""
        q_vec = embedder.encode([q], normalize_embeddings=True)[0].tolist()
        return hybrid_retriever.retrieve(q, q_vec, top_k=20)

    direct_docs = get_hybrid_docs(query)

    final_candidates = direct_docs
    if settings.HYDE_ENABLED:
        # HyDE uses the primary chat model with EXPLICIT credentials so it
        # never falls back to a stale OPENAI_API_KEY from the shell.
        hyde_model = (
            settings.LLM_MODEL
            if settings.HYDE_LLM_MODEL == "LLM_MODEL"
            else settings.HYDE_LLM_MODEL
        )
        hyde_llm = ChatOpenAI(
            model=hyde_model,
            api_key=settings.API_KEY,
            base_url=settings.BASE_URL,
            temperature=0.0,
            timeout=60.0,
            max_retries=1,
        )
        hyde_retriever = HyDERetriever(
            llm=hyde_llm,
            hybrid_retriever_func=get_hybrid_docs,
            score_threshold=settings.HYDE_SCORE_THRESHOLD,
        )
        final_candidates = hyde_retriever.retrieve_with_fallback(query, direct_docs)

    if not final_candidates:
        return SearchResponse(results=[], cache_hit=False)

    # 5. Rerank (Cross-Encoder, lazy-loaded on first use)
    reranker = get_reranker(app)
    reranked_docs = reranker.rerank(query, final_candidates, top_k=20)

    # 6. MMR Selection (Diversity)
    final_docs = mmr_select(
        query_embedding=np.array(query_vector),
        documents=reranked_docs,
        embedder=embedder,
        top_k=top_k,
        lambda_param=diversity,
    )

    # 7. Build response
    results = [
        {
            "text": doc.page_content,
            "source": doc.metadata.get("source", ""),
            "chunk_id": doc.metadata.get("chunk_id", ""),
            "used_hyde": doc.metadata.get("used_hyde", False),
        }
        for doc in final_docs
    ]

    # 8. Update Semantic Cache
    combined_text = "\n\n".join([r["text"] for r in results])
    semantic_cache.set(query_vector, combined_text)

    return SearchResponse(results=results, cache_hit=False)


@router.get("/health")
def health() -> dict[str, str]:
    """
    Health check endpoint.

    Returns:
        Simple status payload.
    """
    return {"status": "healthy"}


@router.get("/cache/stats")
def cache_stats(services: dict[str, Any] = Depends(get_services)) -> dict[str, Any]:
    """
    Expose semantic cache statistics (hits, misses, hit rate, TTL).

    Args:
        services: Shared objects resolved by get_services.

    Returns:
        Cache statistics dict.
    """
    return services["semantic_cache"].stats()
