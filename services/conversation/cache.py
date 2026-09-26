# ============================================
# services/conversation/cache.py
# ============================================
"""
Redis Cloud cache with graceful degradation.

When REDIS_ENABLED is false every method is a safe no-op. When enabled but
Redis is unreachable (not started yet, restarting, network blip...), the
service degrades to no-cache mode AND keeps retrying to connect lazily (at
most once per RETRY_INTERVAL_SECONDS) — a slow-starting Redis is picked up
automatically, without restarting this service.
"""

import json
import logging
import time
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from .settings import settings

logger = logging.getLogger(__name__)


class RedisCacheService:
    """JSON cache with TTL and pattern deletion; degrades to no-cache mode."""

    # Minimum gap between two reconnection attempts while Redis is unreachable.
    # Bounds the cost of the (blocking, <= 2s) connect+ping when Redis is down.
    RETRY_INTERVAL_SECONDS = 5.0

    def __init__(self):
        """Connect to Redis when enabled; retry lazily if it is not up yet."""
        self._enabled = settings.REDIS_ENABLED
        self._default_ttl = settings.REDIS_TTL_SECONDS
        self._client: Redis | None = None
        self._next_retry_at = 0.0  # time.monotonic() deadline for the next attempt

        if not self._enabled:
            logger.info("[RedisCache] Disabled by configuration")
            return
        self._connect()

    def _connect(self) -> None:
        """
        Open a connection and ping Redis; schedule a retry on failure.

        Called from __init__ and lazily from _ensure_client(). Concurrent
        calls are benign: each builds an independent client, the last wins.
        """
        if not settings.REDIS_URL:
            logger.warning("[RedisCache] REDIS_URL is empty, running without cache")
            self._next_retry_at = time.monotonic() + self.RETRY_INTERVAL_SECONDS
            return

        try:
            client = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            client.ping()
        except RedisError as error:
            logger.warning(
                "[RedisCache] Unavailable, running without cache (retrying every %ss): %s",
                int(self.RETRY_INTERVAL_SECONDS),
                error,
            )
            self._client = None
            self._next_retry_at = time.monotonic() + self.RETRY_INTERVAL_SECONDS
            return
        self._client = client
        logger.info("[RedisCache] Connected successfully")

    def _ensure_client(self) -> Redis | None:
        """
        Return the live Redis client, reconnecting lazily after the cooldown.

        Returns:
            The connected client, or None when the cache is disabled by
            configuration or Redis is still unreachable — callers treat None
            as "no cache" and keep working.
        """
        if self._client is not None:
            return self._client
        if not self._enabled or time.monotonic() < self._next_retry_at:
            return None
        self._connect()
        return self._client

    @property
    def enabled(self) -> bool:
        """Whether the cache is actually usable right now (connected)."""
        return self._client is not None

    def get_json(self, key: str) -> Any | None:
        """
        Read one cached JSON value.

        Args:
            key: Cache key.

        Returns:
            The decoded value, or None on miss/error/disabled cache.
        """
        client = self._ensure_client()
        if client is None:
            return None
        try:
            raw = client.get(key)
            return json.loads(raw) if raw is not None else None
        except (RedisError, json.JSONDecodeError) as error:
            logger.warning("[RedisCache] get_json failed for key=%s: %s", key, error)
            return None

    def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """
        Write one JSON value with a TTL.

        Args:
            key: Cache key.
            value: JSON-serializable value.
            ttl_seconds: Optional TTL override; defaults to settings.REDIS_TTL_SECONDS.
        """
        client = self._ensure_client()
        if client is None:
            return
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        try:
            payload = json.dumps(value, ensure_ascii=False, default=str)
            if ttl and ttl > 0:
                client.setex(key, ttl, payload)
            else:
                client.set(key, payload)
        except (RedisError, TypeError, ValueError) as error:
            logger.warning("[RedisCache] set_json failed for key=%s: %s", key, error)

    def delete(self, key: str) -> None:
        """
        Delete one cache key (best-effort).

        Args:
            key: Cache key.
        """
        client = self._ensure_client()
        if client is None:
            return
        try:
            client.delete(key)
        except RedisError as error:
            logger.warning("[RedisCache] delete failed for key=%s: %s", key, error)

    def delete_pattern(self, pattern: str) -> None:
        """
        Delete all keys matching a glob pattern using SCAN (non-blocking).

        Args:
            pattern: Glob pattern, e.g. 'conversation:<id>:*'.
        """
        client = self._ensure_client()
        if client is None:
            return
        try:
            keys = list(client.scan_iter(match=pattern))
            if keys:
                client.delete(*keys)
        except RedisError as error:
            logger.warning(
                "[RedisCache] delete_pattern failed for pattern=%s: %s", pattern, error
            )
