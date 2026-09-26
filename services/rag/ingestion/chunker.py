# ============================================
# services/rag/ingestion/chunker.py
# ============================================
"""
Semantic chunking and Qdrant indexing logic.
"""

import logging
import re
import time

import numpy as np
from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

UPSERT_BATCH_SIZE = 64
UPSERT_MAX_ATTEMPTS = 3
UPSERT_TIMEOUT_SECONDS = 120


def split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences using regex on punctuation.
    """
    pattern = r"(?<=[.!?])\s+"
    raw_sentences = re.split(pattern, text)
    return [s.strip() for s in raw_sentences if len(s.strip()) > 2]


def semantic_chunking(
    text: str,
    embedder: SentenceTransformer,
    threshold: float,
    source: str,
) -> list[Document]:
    """
    Split text into semantic chunks based on cosine similarity between consecutive sentences.
    """
    sentences = split_into_sentences(text)
    if not sentences:
        return []

    embeddings = embedder.encode(sentences)
    chunks: list[str] = []
    current_chunk: list[str] = [sentences[0]]

    for i in range(len(sentences) - 1):
        sim = np.dot(embeddings[i], embeddings[i + 1]) / (
            np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[i + 1])
        )
        if sim < threshold:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentences[i + 1]]
        else:
            current_chunk.append(sentences[i + 1])

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return [
        Document(page_content=chunk, metadata={"source": source, "chunk_id": i})
        for i, chunk in enumerate(chunks)
    ]


def index_to_qdrant(
    docs: list[Document],
    embedder: SentenceTransformer,
    client: QdrantClient,
    collection_name: str,
    vector_size: int,
) -> None:
    """
    Index a list of documents into Qdrant, replacing the existing collection
    (full re-index semantics of the initial KB ingestion).
    """
    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )

    texts = [doc.page_content for doc in docs]
    embeddings = embedder.encode(texts).tolist()

    points = [
        PointStruct(
            id=i,
            vector=embedding,
            payload={"text": text, **docs[i].metadata},
        )
        for i, (embedding, text) in enumerate(zip(embeddings, texts))
    ]

    for start in range(0, len(points), UPSERT_BATCH_SIZE):
        batch = points[start : start + UPSERT_BATCH_SIZE]
        for attempt in range(1, UPSERT_MAX_ATTEMPTS + 1):
            try:
                client.upsert(
                    collection_name=collection_name,
                    points=batch,
                    wait=True,
                    timeout=UPSERT_TIMEOUT_SECONDS,
                )
                break
            except ResponseHandlingException:
                if attempt == UPSERT_MAX_ATTEMPTS:
                    raise
                delay_seconds = 2**attempt
                logger.warning(
                    "Qdrant batch %d-%d timed out; retrying in %ds (%d/%d)",
                    start,
                    start + len(batch) - 1,
                    delay_seconds,
                    attempt,
                    UPSERT_MAX_ATTEMPTS,
                )
                time.sleep(delay_seconds)

    indexed_count = client.get_collection(collection_name).points_count
    if indexed_count != len(points):
        raise RuntimeError(
            f"Qdrant indexed {indexed_count} points, expected {len(points)}"
        )
