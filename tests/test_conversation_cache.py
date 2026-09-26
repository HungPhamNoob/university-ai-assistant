"""Unit tests for the conversation service Redis Cloud connection contract."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.conversation.cache import RedisCacheService
from services.conversation.settings import settings


def test_cache_connects_with_redis_url(monkeypatch) -> None:
    """The managed Redis URI must be passed to redis-py without splitting credentials."""
    redis_url = "redis://default:test-password@redis.example.com:19999/0"
    redis_client = MagicMock()
    from_url = MagicMock(return_value=redis_client)

    monkeypatch.setattr(settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(settings, "REDIS_URL", redis_url)
    monkeypatch.setattr("services.conversation.cache.Redis.from_url", from_url)

    cache = RedisCacheService()

    assert cache.enabled is True
    redis_client.ping.assert_called_once_with()
    from_url.assert_called_once_with(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def test_cache_falls_back_when_redis_url_is_empty(monkeypatch) -> None:
    """An incomplete deployment must keep database-backed requests available."""
    monkeypatch.setattr(settings, "REDIS_ENABLED", True)
    monkeypatch.setattr(settings, "REDIS_URL", "")

    cache = RedisCacheService()

    assert cache.enabled is False
