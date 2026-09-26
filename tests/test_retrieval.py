# ============================================
# tests/test_retrieval.py
# ============================================
"""
Integration tests for the RAG Retrieval pipeline.
Tests real API calls to FastAPI and Qdrant Cloud interactions.
"""

import os
import time

import httpx
import pytest
from dotenv import load_dotenv

# Load environment variables from root .env file
load_dotenv()

# Configuration for testing
BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8002")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# Sample queries for testing
QUERY_GENERAL = "UET yêu cầu gì khi dùng AI cho quyết định có ảnh hưởng lớn?"
QUERY_OBSCURE = "Địa chỉ đường phố chính xác của phòng GD3-402 là gì?"


@pytest.fixture(scope="session", autouse=True)
def clear_semantic_cache():
    """Clear the semantic cache before the suite so the first search is a guaranteed miss."""
    from qdrant_client import QdrantClient
    from qdrant_client.http.exceptions import ResponseHandlingException

    cache_collection = os.getenv("QDRANT_CACHE_COLLECTION", "uet_hr_cache")
    timeout = float(os.getenv("QDRANT_TIMEOUT_SECONDS", "30"))
    attempts = max(1, int(os.getenv("QDRANT_STARTUP_RETRIES", "3")))
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=timeout)

    for attempt in range(1, attempts + 1):
        try:
            if client.collection_exists(cache_collection):
                points, _ = client.scroll(
                    collection_name=cache_collection,
                    limit=10000,
                    with_payload=False,
                )
                if points:
                    client.delete(
                        collection_name=cache_collection,
                        points_selector=[point.id for point in points],
                    )
            break
        except ResponseHandlingException:
            if attempt == attempts:
                raise
            time.sleep(attempt * 2)
    yield


class TestRAGRetrieval:
    """Test suite for RAG retrieval endpoints."""

    @pytest.fixture
    def client(self):
        """Create an async HTTP client for testing."""
        # A cold first search may load the cross-encoder and invoke HyDE.
        # Match the agent service's production RAG timeout instead of failing
        # while the server is still completing valid work.
        return httpx.AsyncClient(base_url=BASE_URL, timeout=180.0)

    @pytest.mark.asyncio
    async def test_health_check(self, client: httpx.AsyncClient):
        """Test if the RAG service is healthy and reachable."""
        response = await client.get("/api/kb/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_search_basic_retrieval(self, client: httpx.AsyncClient):
        """Test basic search functionality with a standard query."""
        payload = {"query": QUERY_GENERAL, "top_k": 3, "diversity": 0.7}
        response = await client.post("/api/kb/search", json=payload)

        assert response.status_code == 200
        data = response.json()

        assert "results" in data
        assert len(data["results"]) > 0
        assert data["cache_hit"] is False  # First call should be a miss

        # Check structure of results
        first_result = data["results"][0]
        assert "text" in first_result
        assert "source" in first_result
        assert "chunk_id" in first_result

    @pytest.mark.asyncio
    async def test_semantic_cache_hit(self, client: httpx.AsyncClient):
        """Test if repeating the same query triggers a cache hit."""
        payload = {"query": QUERY_GENERAL, "top_k": 3, "diversity": 0.7}

        # First call (already done in previous test, but ensuring state here)
        await client.post("/api/kb/search", json=payload)

        # Second call should hit cache
        response = await client.post("/api/kb/search", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["cache_hit"] is True
        assert len(data["results"]) > 0

    @pytest.mark.asyncio
    async def test_hyde_fallback_trigger(self, client: httpx.AsyncClient):
        """Test if HyDE is triggered for low-confidence queries."""
        # Use an obscure query that likely yields low BM25/Dense scores
        payload = {"query": QUERY_OBSCURE, "top_k": 3, "diversity": 0.7}

        response = await client.post("/api/kb/search", json=payload)
        assert response.status_code == 200
        data = response.json()

        # Even if HyDE fails or doesn't find anything, the API should return gracefully
        # We check metadata to see if HyDE was attempted (if implemented in response)
        if data["results"]:
            used_hyde = any(r.get("used_hyde", False) for r in data["results"])
            print(f"HyDE was triggered: {used_hyde}")

    @pytest.mark.asyncio
    async def test_invalid_query_handling(self, client: httpx.AsyncClient):
        """Test API behavior with empty or invalid input."""
        payload = {"query": "", "top_k": 3, "diversity": 0.7}
        response = await client.post("/api/kb/search", json=payload)

        # Depending on your validation, this might be 422 or 200 with empty results
        assert response.status_code in [200, 422]


if __name__ == "__main__":
    pytest.main(["-v", "tests/test_retrieval.py"])

# fuser -k 8002/tcp
# uv run uvicorn services.rag.main:app --reload --port 8002

# uv run pytest tests/test_retrieval.py -v
