# ============================================
# services/rag/retrieval/hybrid.py
# ============================================
"""
Hybrid retrieval combining dense (Qdrant) and sparse (BM25) with RRF fusion.
"""

import hashlib

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from qdrant_client import QdrantClient


def get_doc_hash(doc: Document) -> str:
    """Generate a stable hash for a document to prevent RRF duplicates."""
    if "chunk_id" in doc.metadata:
        return str(doc.metadata["chunk_id"])
    return hashlib.md5(doc.page_content.encode("utf-8")).hexdigest()


def rrf_fusion(doc_lists: list[list[Document]], k: int = 60) -> list[Document]:
    """
    Fuse multiple ranked document lists using Reciprocal Rank Fusion (RRF).
    """
    scores: dict[str, float] = {}
    doc_map: dict[str, Document] = {}

    for docs in doc_lists:
        for rank, doc in enumerate(docs):
            doc_id = get_doc_hash(doc)
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            existing = doc_map.get(doc_id)
            if existing is None:
                doc_map[doc_id] = doc
                continue

            # The sparse copy has no vector similarity score. Preserve the
            # dense metadata when the same chunk appears in both rankings so
            # HyDE evaluates real confidence instead of an artificial zero.
            doc_map[doc_id] = Document(
                page_content=existing.page_content,
                metadata={**doc.metadata, **existing.metadata},
            )

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return [doc_map[doc_id] for doc_id in sorted_ids]


class HybridRetriever:
    """Performs hybrid search using dense and sparse retrieval, fused with RRF."""

    def __init__(
        self,
        documents: list[Document],
        qdrant_client: QdrantClient,
        collection_name: str,
    ):
        self.bm25 = BM25Retriever.from_documents(documents, k=20)
        self.qdrant = qdrant_client
        self.collection_name = collection_name

    def retrieve(
        self, query: str, query_vector: list[float], top_k: int = 20
    ) -> list[Document]:
        """Retrieve candidate documents using both sparse and dense methods."""
        # Sparse retrieval (BM25)
        sparse_docs = self.bm25.invoke(query)

        # Dense retrieval (Qdrant)
        dense_hits = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
        ).points
        dense_docs = [
            Document(
                page_content=hit.payload["text"],
                # Carry the Qdrant similarity score into metadata so the HyDE
                # trigger ("avg top-3 score below threshold") can actually see it.
                metadata={**hit.payload, "score": hit.score},
            )
            for hit in dense_hits
        ]

        return rrf_fusion([dense_docs, sparse_docs])
