# ============================================
# services/rag/retrieval/cache.py
# ============================================
"""
Semantic response cache backed by Qdrant. This is separate from the Redis
Cloud exact-match cache used by the conversation service.

Design notes:
- Every entry stores the query embedding plus payload {answer, timestamp}.
- TTL is enforced at READ time with a payload range filter, so expired entries
  are never served even before cleanup runs (safe on Qdrant Cloud).
- `cleanup_expired()` deletes old points on demand (payload index on the
  'timestamp' field is created automatically at init).
- Simple hit/miss/set counters expose cache statistics for observability.
"""

import logging
import time
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    PayloadSchemaType,
    PointStruct,
    Range,
    VectorParams,
)

logger = logging.getLogger(__name__)


class QdrantSemanticCache:
    """Semantic cache with TTL-based eviction and usage statistics."""

    def __init__(
        self,
        client: QdrantClient,
        collection_name: str,
        ttl_seconds: int,
        vector_size: int,
    ):
        """
        Create the cache collection (and its TTL payload index) when missing.

        Args:
            client: Connected Qdrant client.
            collection_name: Dedicated collection for cached query/answer pairs.
            ttl_seconds: Time-to-live for each cached entry.
            vector_size: Dimension of the query embeddings.
        """
        self.client = client
        self.collection_name = collection_name
        self.ttl = ttl_seconds
        self.hits = 0
        self.misses = 0
        self.sets = 0

        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

        # Qdrant Cloud requires a payload index on 'timestamp' for range filters.
        collection_info = self.client.get_collection(self.collection_name)
        if "timestamp" not in collection_info.payload_schema:
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="timestamp",
                field_schema=PayloadSchemaType.FLOAT,
                wait=True,
            )

    def get(self, query_vector: list[float], threshold: float = 0.95) -> str | None:
        """
        Look up a cached answer for a semantically similar, non-expired query.

        Args:
            query_vector: Embedding of the incoming query.
            threshold: Minimum cosine similarity to count as a cache hit.

        Returns:
            The cached answer string, or None on miss.
        """
        expire_before = time.time() - self.ttl
        try:
            hits = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=Filter(
                    must=[
                        FieldCondition(key="timestamp", range=Range(gt=expire_before))
                    ]
                ),
                limit=1,
                score_threshold=threshold,
            ).points
        except Exception as error:  # noqa: BLE001 - cache must never break retrieval
            logger.warning("Semantic cache read failed: %s", error)
            self.misses += 1
            return None

        if hits:
            self.hits += 1
            return hits[0].payload.get("answer")
        self.misses += 1
        return None

    def set(self, query_vector: list[float], answer: str) -> None:
        """
        Store a query/answer pair with the current timestamp.

        Args:
            query_vector: Embedding of the original query.
            answer: Final retrieval result to reuse for similar queries.
        """
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=str(uuid.uuid4()),
                        vector=query_vector,
                        payload={"answer": answer, "timestamp": time.time()},
                    )
                ],
            )
            self.sets += 1
        except Exception as error:  # noqa: BLE001 - cache writes are best-effort
            logger.warning("Semantic cache write failed: %s", error)

    def cleanup_expired(self) -> int:
        """
        Delete all entries older than the TTL (best-effort).

        Returns:
            Number of expired points removed.
        """
        expire_before = time.time() - self.ttl
        try:
            expired = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="timestamp", range=Range(lte=expire_before))
                    ]
                ),
                limit=1000,
                with_payload=False,
                with_vectors=False,
            )[0]
            if not expired:
                return 0
            expired_ids = [point.id for point in expired]
            self.client.delete(
                collection_name=self.collection_name, points_selector=expired_ids
            )
            logger.info(
                "Semantic cache cleanup removed %d expired entries", len(expired_ids)
            )
            return len(expired_ids)
        except Exception as error:  # noqa: BLE001 - cleanup must never crash the API
            logger.warning("Semantic cache cleanup failed: %s", error)
            return 0

    def stats(self) -> dict[str, Any]:
        """
        Return cache statistics for observability.

        Returns:
            Dict with hits, misses, sets, hit_rate and ttl_seconds.
        """
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
            "ttl_seconds": self.ttl,
        }
