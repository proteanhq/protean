"""Idempotency store for command deduplication.

A lightweight utility wrapping Redis to track command processing status.
Used internally by domain.process() and EventStoreSubscription to implement
submission-level and subscription-level dedup.

When Redis is not configured (redis_url is None), all operations are no-ops
and the system behaves as if idempotency is disabled.
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class IdempotencyStore:
    """Redis-backed idempotency cache for command deduplication.

    Stores entries keyed as ``idempotency:{key}`` with JSON payloads
    containing status, result, and error information. Entries have
    configurable TTL.

    Falls back gracefully when Redis is not configured — all check/record
    operations become no-ops.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        ttl: int = 86400,
        error_ttl: int = 60,
    ) -> None:
        self._redis = None
        self._ttl = ttl
        self._error_ttl = error_ttl

        if redis_url:
            try:
                import redis

                self._redis = redis.Redis.from_url(redis_url)
                self._redis.ping()
                logger.info("Idempotency store connected to Redis at %s", redis_url)
            except Exception:
                logger.warning(
                    "Could not connect to Redis at %s — idempotency dedup is disabled",
                    redis_url,
                    exc_info=True,
                )
                self._redis = None
        else:
            logger.debug("No redis_url configured for idempotency — dedup is disabled")

    @property
    def is_active(self) -> bool:
        """Whether the store has an active Redis connection."""
        return self._redis is not None

    def _key(self, idempotency_key: str) -> str:
        return f"idempotency:{idempotency_key}"

    def check(self, idempotency_key: str) -> Optional[dict[str, Any]]:
        """Look up an idempotency record.

        Returns:
            A dict with ``status``, ``result`` (or ``error``), or None if
            no record exists (or Redis is unavailable).
        """
        if not self._redis:
            return None

        try:
            raw = self._redis.get(self._key(idempotency_key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            logger.warning(
                "Idempotency check failed for key %s — proceeding without dedup",
                idempotency_key,
                exc_info=True,
            )
            return None

    def record_success(
        self,
        idempotency_key: str,
        result: Any,
        ttl: Optional[int] = None,
    ) -> None:
        """Record a successful command processing.

        Args:
            idempotency_key: The caller-provided idempotency key.
            result: The handler result (must be JSON-serializable).
            ttl: Override the default TTL (seconds).
        """
        if not self._redis:
            return

        ttl = ttl if ttl is not None else self._ttl
        entry = json.dumps({"status": "success", "result": result})
        try:
            self._redis.setex(self._key(idempotency_key), ttl, entry)
        except Exception:
            logger.warning(
                "Failed to record idempotency success for key %s",
                idempotency_key,
                exc_info=True,
            )

    def record_error(
        self,
        idempotency_key: str,
        error: str,
        ttl: Optional[int] = None,
    ) -> None:
        """Record a failed command processing with a short TTL.

        The short TTL allows retries after the error entry expires.

        Args:
            idempotency_key: The caller-provided idempotency key.
            error: A string description of the error.
            ttl: Override the default error TTL (seconds).
        """
        if not self._redis:
            return

        ttl = ttl if ttl is not None else self._error_ttl
        entry = json.dumps({"status": "error", "error": error})
        try:
            self._redis.setex(self._key(idempotency_key), ttl, entry)
        except Exception:
            logger.warning(
                "Failed to record idempotency error for key %s",
                idempotency_key,
                exc_info=True,
            )

    def flush(self) -> None:
        """Remove all idempotency entries. Useful for testing."""
        if not self._redis:
            return

        try:
            self._redis.flushdb()
        except Exception:
            logger.warning("Failed to flush idempotency store", exc_info=True)
