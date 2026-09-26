# ============================================
# services/rag/retrieval/mmr.py
# ============================================
"""
Maximal Marginal Relevance (MMR) for diversity selection.
"""

import numpy as np
from langchain_core.documents import Document
from sentence_transformers import SentenceTransformer


def mmr_select(
    query_embedding: np.ndarray,
    documents: list[Document],
    embedder: SentenceTransformer,
    top_k: int = 5,
    lambda_param: float = 0.7,
) -> list[Document]:
    """
    Select documents maximizing relevance and diversity using MMR.
    """
    if not documents:
        return []

    doc_texts = [doc.page_content for doc in documents]
    doc_embeddings = embedder.encode(doc_texts, normalize_embeddings=True)

    query_sims = np.dot(doc_embeddings, query_embedding)
    selected_indices: list[int] = []
    candidate_indices = list(range(len(documents)))

    while len(selected_indices) < top_k and candidate_indices:
        best_score = -float("inf")
        best_idx = -1

        for idx in candidate_indices:
            relevance = query_sims[idx]

            if not selected_indices:
                max_sim_to_selected = 0.0
            else:
                selected_embs = doc_embeddings[selected_indices]
                sims_to_selected = np.dot(selected_embs, doc_embeddings[idx])
                max_sim_to_selected = float(np.max(sims_to_selected))

            score = (lambda_param * relevance) - (
                (1 - lambda_param) * max_sim_to_selected
            )

            if score > best_score:
                best_score = score
                best_idx = idx

        selected_indices.append(best_idx)
        candidate_indices.remove(best_idx)

    return [documents[i] for i in selected_indices]
