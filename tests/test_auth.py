# ============================================
# tests/test_auth.py
# Integration tests for the identity service.
#
# Run the dev stack first:
#   docker compose -f configs/docker-compose.dev.yml up -d postgres identity
#   TEST_IDENTITY_URL=http://localhost:8001 pytest tests/test_auth.py -v
#
# What we cover:
#   1. Health check.
#   2. Register -> 201 + JWT token + user payload.
#   3. Register with the same email again -> 409.
#   4. Register with an invalid email -> 422.
#   5. Login -> 200 + token.
#   6. Login with a wrong password -> 401.
#   7. GET /auth/me with a Bearer token -> 200.
#   8. GET /auth/me without credentials -> 401.
#   9. GET /auth/me with the X-User-Id header injected by Kong -> 200.
# ============================================
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

# Identity service URL. Override with TEST_IDENTITY_URL if needed.
BASE_URL = "http://localhost:8001"

# A unique email per test run so tests stay repeatable.
TEST_EMAIL = f"test_{uuid.uuid4().hex[:10]}@example.com"
TEST_PASSWORD = "Secret123!"
TEST_NAME = "Test User"


@pytest.fixture(scope="module")
def base_url() -> str:
    import os

    return os.getenv("TEST_IDENTITY_URL", BASE_URL)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    # One client per test: pytest-asyncio runs every test on its own
    # event loop, so a shared client would die with "Event loop is closed".
    async with httpx.AsyncClient(timeout=30.0) as async_client:
        yield async_client


def _payload() -> dict:
    """Registration request body."""
    return {
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "name": TEST_NAME,
        "role": "student",
    }


# ---------- 1. Health check ----------
@pytest.mark.asyncio
async def test_health_check(base_url: str, client: httpx.AsyncClient) -> None:
    response = await client.get(f"{base_url}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------- 2. Register a new user ----------
@pytest.mark.asyncio
async def test_register_returns_token(base_url: str, client: httpx.AsyncClient) -> None:
    response = await client.post(f"{base_url}/auth/register", json=_payload())
    assert response.status_code == 201, response.text

    data = response.json()
    assert data["token_type"] == "bearer"
    assert len(data["token"]) > 0
    assert data["user"]["email"] == TEST_EMAIL
    assert data["user"]["name"] == TEST_NAME
    assert data["user"]["user_id"]


# ---------- 3. Duplicate email is rejected ----------
@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(
    base_url: str, client: httpx.AsyncClient
) -> None:
    response = await client.post(f"{base_url}/auth/register", json=_payload())
    assert response.status_code == 409


# ---------- 4. Invalid email is rejected ----------
@pytest.mark.asyncio
async def test_register_invalid_email_returns_422(
    base_url: str, client: httpx.AsyncClient
) -> None:
    payload = _payload()
    payload["email"] = "not-an-email"
    response = await client.post(f"{base_url}/auth/register", json=payload)
    assert response.status_code == 422


# ---------- 5. Login with correct credentials ----------
@pytest.mark.asyncio
async def test_login_success_returns_token(
    base_url: str, client: httpx.AsyncClient
) -> None:
    response = await client.post(
        f"{base_url}/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["token"]) > 0
    assert data["user"]["email"] == TEST_EMAIL


# ---------- 6. Login with wrong password ----------
@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(
    base_url: str, client: httpx.AsyncClient
) -> None:
    response = await client.post(
        f"{base_url}/auth/login",
        json={"email": TEST_EMAIL, "password": "WrongPassword1!"},
    )
    assert response.status_code == 401


# ---------- 7. /auth/me with a Bearer token ----------
@pytest.mark.asyncio
async def test_me_with_bearer_token(base_url: str, client: httpx.AsyncClient) -> None:
    # Login first to obtain a fresh token.
    login = await client.post(
        f"{base_url}/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["token"]

    response = await client.get(
        f"{base_url}/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    # /auth/me returns the UserProfile object directly (no wrapper).
    profile = response.json()
    assert profile["email"] == TEST_EMAIL
    assert profile["name"] == TEST_NAME


# ---------- 8. /auth/me without credentials ----------
@pytest.mark.asyncio
async def test_me_without_credentials_returns_401(
    base_url: str, client: httpx.AsyncClient
) -> None:
    response = await client.get(f"{base_url}/auth/me")
    assert response.status_code == 401


# ---------- 9. /auth/me with the gateway-injected X-User-Id header ----------
@pytest.mark.asyncio
async def test_me_with_gateway_header(base_url: str, client: httpx.AsyncClient) -> None:
    # Kong resolves the JWT and forwards only X-User-Id to the backends.
    # Login to obtain the user_id of the account created in earlier tests.
    login = await client.post(
        f"{base_url}/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert login.status_code == 200
    user_id = login.json()["user"]["user_id"]

    response = await client.get(f"{base_url}/auth/me", headers={"X-User-Id": user_id})
    assert response.status_code == 200, response.text
    assert response.json()["user_id"] == user_id
