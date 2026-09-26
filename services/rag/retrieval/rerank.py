# ============================================
# services/rag/retrieval/rerank.py
# ============================================
"""
Cross-encoder reranking module.
"""

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder


class Reranker:
    """Wrapper around a cross-encoder model for reranking documents."""

    def __init__(self, model_name: str):
        self.model = CrossEncoder(model_name)

    def rerank(
        self, query: str, documents: list[Document], top_k: int = 20
    ) -> list[Document]:
        """Rerank documents based on relevance to the query."""
        if not documents:
            return []

        pairs = [[query, doc.page_content] for doc in documents]
        scores = self.model.predict(pairs)

        scored_docs: list[tuple[float, Document]] = list(zip(scores, documents))
        scored_docs.sort(key=lambda x: x[0], reverse=True)

        return [doc for _, doc in scored_docs[:top_k]]
