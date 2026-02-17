"""Tracing instrumentation for the Protean Engine.

Emits structured MessageTrace events to Redis Pub/Sub as messages flow through
the outbox → Redis Streams → handler pipeline. The Observatory server subscribes
to this channel to power the real-time dashboard, SSE endpoint, and Prometheus metrics.

Zero overhead when nobody is listening — the emitter checks subscriber count
and short-circuits before any serialization.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Redis Pub/Sub channel for trace events
TRACE_CHANNEL = "protean:trace"

# How often (seconds) to check if anyone is subscribed
_SUBSCRIBER_CHECK_TTL = 2.0


@dataclass
class MessageTrace:
    """Structured event representing one stage of a message's journey through the pipeline."""

    event: str  # "outbox.published", "handler.completed", etc.
    domain: str  # "identity", "catalogue"
    stream: str  # "identity::customer"
    message_id: str  # Domain event/command UUID
    message_type: str  # "CustomerRegistered"
    status: str  # "ok", "error", "retry"
    handler: Optional[str] = None  # "CustomerProjector"
    duration_ms: Optional[float] = None  # Processing time (handler stages)
    error: Optional[str] = None  # Error message for failures
    metadata: Optional[dict] = field(default_factory=dict)  # Extra context
    timestamp: str = ""  # ISO 8601, filled automatically

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_json(self) -> str:
        """Serialize to JSON for Redis Pub/Sub transport."""
        return json.dumps(asdict(self), default=str)


class TraceEmitter:
    """Lightweight emitter that publishes MessageTrace events to Redis Pub/Sub.

    Attached to the Engine and passed to OutboxProcessor and StreamSubscription.
    Uses conditional emission — checks PUBSUB NUMSUB periodically and skips
    all work when nobody is listening.
    """

    def __init__(self, domain) -> None:
        self._domain = domain
        self._domain_name = domain.name
        self._redis = None
        self._has_subscribers = False
        self._last_subscriber_check = 0.0
        self._initialized = False

    def _ensure_initialized(self) -> bool:
        """Lazily initialize Redis connection from the domain's broker."""
        if self._initialized:
            return self._redis is not None

        self._initialized = True
        try:
            broker = self._domain.brokers.get("default")
            if broker and hasattr(broker, "redis_instance"):
                self._redis = broker.redis_instance
                return True
        except Exception as e:
            logger.debug(f"TraceEmitter: Redis not available ({e})")

        return False

    def _check_subscribers(self) -> bool:
        """Check if anyone is subscribed to the trace channel. Cached for efficiency."""
        now = time.monotonic()
        if now - self._last_subscriber_check < _SUBSCRIBER_CHECK_TTL:
            return self._has_subscribers

        self._last_subscriber_check = now

        if not self._ensure_initialized():
            self._has_subscribers = False
            return False

        try:
            # PUBSUB NUMSUB returns pairs of [channel, count]
            result = self._redis.pubsub_numsub(TRACE_CHANNEL)
            # result is a list of tuples: [(channel, count)]
            count = result[0][1] if result else 0
            self._has_subscribers = count > 0
        except Exception:
            self._has_subscribers = False

        return self._has_subscribers

    def emit(
        self,
        event: str,
        stream: str,
        message_id: str,
        message_type: str,
        status: str = "ok",
        handler: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Emit a trace event. No-op when nobody is listening."""
        if not self._check_subscribers():
            return

        try:
            trace = MessageTrace(
                event=event,
                domain=self._domain_name,
                stream=stream,
                message_id=message_id,
                message_type=message_type,
                status=status,
                handler=handler,
                duration_ms=duration_ms,
                error=error,
                metadata=metadata or {},
            )
            self._redis.publish(TRACE_CHANNEL, trace.to_json())
        except Exception as e:
            # Never let tracing failures affect message processing
            logger.debug(f"TraceEmitter publish failed: {e}")
