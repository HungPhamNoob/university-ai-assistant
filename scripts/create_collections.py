# ============================================
# scripts/create_collections.py
# ============================================
"""
Idempotent Qdrant collection bootstrap.

Creates the knowledge-base collection and the semantic cache collection when
they do not exist yet. Episodic memory is SQL-only (independent per thread),
so there is no episodes collection anymore. Safe to run repeatedly:
    python scripts/create_collections.py
"""

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(
    0, str(_REPO_ROOT)
)  # để import services.* khi chạy `python scripts/...`
load_dotenv(_REPO_ROOT / ".env")

import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def ensure_collection(client: QdrantClient, name: str, vector_size: int) -> None:
    """
    Create one collection when missing.

    Args:
        client: Connected Qdrant client.
        name: Collection name.
        vector_size: Dense vector dimension.
    """
    if client.collection_exists(name):
        logger.info("Collection '%s' already exists", name)
        return
    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    logger.info("Collection '%s' created", name)


def main() -> None:
    """Create the KB and semantic-cache collections (idempotent)."""
    client = QdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ["QDRANT_API_KEY"],
    )
    vector_size = int(os.environ.get("VECTOR_SIZE", "384"))
    ensure_collection(
        client, os.environ.get("QDRANT_KB_COLLECTION", "uet_hr_docs"), vector_size
    )
    ensure_collection(
        client, os.environ.get("QDRANT_CACHE_COLLECTION", "uet_hr_cache"), vector_size
    )
    logger.info("Qdrant collections ready.")


if __name__ == "__main__":
    main()
