# ============================================
# services/rag/retrieval/hyde.py
# ============================================
"""
Hypothetical Document Embeddings (HyDE) fallback logic.
Simplified for production: triggers only when direct retrieval confidence is low.
"""

import logging

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger(__name__)

HYDE_PROMPT = PromptTemplate.from_template(
    "Please write a concise, factual passage that answers the following question. "
    "Do not include conversational filler. Just provide the hypothetical document content.\n"
    "Question: {query}"
)


class HyDERetriever:
    """Handles HyDE generation and fallback retrieval."""

    def __init__(
        self, llm: BaseChatModel, hybrid_retriever_func, score_threshold: float
    ):
        """
        Args:
            llm: Language model to generate hypothetical documents.
            hybrid_retriever_func: Callable that takes a query string and returns List[Document].
            score_threshold: Minimum average score to avoid triggering HyDE.
        """
        self.llm = llm
        self.hybrid_retriever_func = hybrid_retriever_func
        self.score_threshold = score_threshold

    def _calculate_avg_score(self, documents: list[Document], top_k: int = 3) -> float:
        """Calculate average Qdrant score of top documents."""
        top_docs = documents[:top_k]
        if not top_docs:
            return 0.0

        scores = [float(doc.metadata.get("score", 0.0)) for doc in top_docs]
        return sum(scores) / len(scores)

    def retrieve_with_fallback(
        self, query: str, direct_docs: list[Document]
    ) -> list[Document]:
        """
        Evaluate direct retrieval. If score is low, generate a hypothetical document and retrieve again.
        """
        avg_score = self._calculate_avg_score(direct_docs)

        if avg_score >= self.score_threshold:
            logger.info(
                f"HyDE skipped: direct retrieval score {avg_score:.4f} >= threshold"
            )
            return direct_docs

        logger.info(
            f"HyDE triggered: direct retrieval score {avg_score:.4f} < threshold"
        )

        try:
            # Generate hypothetical document
            response = self.llm.invoke(HYDE_PROMPT.format(query=query))
            hypothetical_text = (
                response.content if hasattr(response, "content") else str(response)
            )

            # Retrieve using the hypothetical text
            hyde_docs = self.hybrid_retriever_func(hypothetical_text)

            # Tag metadata for observability
            for doc in hyde_docs:
                doc.metadata["used_hyde"] = True
                doc.metadata["hyde_query"] = hypothetical_text

            logger.info("HyDE retrieval completed successfully.")
            return hyde_docs

        except Exception as e:  # noqa: BLE001 - HyDE generation failure falls back to direct results
            logger.warning(
                f"HyDE generation failed, falling back to direct results: {e}"
            )
            return direct_docs
