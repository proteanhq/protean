"""Tracing instrumentation for the Protean Engine.

Emits structured MessageTrace events to Redis Pub/Sub and persists them to a
time-bounded Redis Stream. The Observatory server subscribes to the Pub/Sub
channel for real-time SSE streaming, and reads the Stream for historical
dashboard data.

Zero overhead when nobody is listening and persistence is disabled — the emitter
checks subscriber count and short-circuits before any serialization.
"""

import json
import logging
import math
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from protean.utils.globals import _domain_now

logger = logging.getLogger(__name__)

# Redis Pub/Sub channel for real-time trace events
TRACE_CHANNEL = "protean:trace"

# Redis Stream for persisted trace history
TRACE_STREAM = "protean:traces"

# Default number of days to retain trace entries in the stream
DEFAULT_TRACE_RETENTION_DAYS = 7

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
    handler: str | None = None  # "CustomerProjector"
    duration_ms: float | None = None  # Processing time (handler stages)
    error: str | None = None  # Error message for failures
    metadata: dict[str, Any] | None = field(default_factory=dict)  # Extra context
    payload: dict[str, Any] | None = None  # Message payload (event/command data)
    worker_id: str | None = None  # Subscription instance that processed this message
    correlation_id: str | None = None  # Correlation chain identifier
    causation_id: str | None = None  # Parent message identifier
    timestamp: str = ""  # ISO 8601, filled automatically

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _domain_now().isoformat()

    def to_json(self) -> str:
        """Serialize to JSON for transport."""
        return json.dumps(asdict(self), default=str)


def decode_trace_payload(raw: object) -> dict[str, Any] | None:
    """Decode one JSON trace payload, as bytes or str.

    Returns ``None`` when the payload is empty, is not UTF-8, is not JSON, or
    is JSON but not an object. A reader skips such an entry. An integer longer
    than Python's digit limit raises ``ValueError`` and very deep nesting raises
    ``RecursionError`` inside ``json.loads``; both count as "not JSON".
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(raw, str) or not raw:
        return None
    try:
        trace = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return trace if isinstance(trace, dict) else None


def trace_number(value: object) -> float | None:
    """Return a numeric trace value as a finite float, or ``None``.

    A number or a numeric string such as ``"12.5"`` counts. A bool does not,
    though Python treats it as an int. Infinity and NaN return ``None``,
    because a JSON response cannot carry them.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def decode_trace(fields: Mapping[Any, Any]) -> dict[str, Any] | None:
    """Decode the trace held in the fields of one trace stream entry.

    The trace is the JSON string under the ``data`` field. Redis returns the
    field name as bytes or as str, depending on how the client decodes
    responses. Returns ``None`` for an entry with no usable trace.
    """
    return decode_trace_payload(fields.get(b"data") or fields.get("data"))


class TraceEmitter:
    """Lightweight emitter that publishes MessageTrace events to Redis.

    Attached to the Engine and passed to OutboxProcessor and StreamSubscription.

    Two output channels:
    - **Pub/Sub** (`protean:trace`): Real-time fan-out for SSE clients.
      Conditional — checks PUBSUB NUMSUB and skips when nobody is listening.
    - **Stream** (`protean:traces`): Time-bounded history for dashboard persistence.
      Always writes when persistence is enabled (trace_retention_days > 0).
      Uses MINID trimming to retain entries for the configured number of days.

    Short-circuits all work when both channels are inactive.
    """

    def __init__(
        self, domain: Any, trace_retention_days: int = DEFAULT_TRACE_RETENTION_DAYS
    ) -> None:
        self._domain = domain
        self._domain_name = domain.name
        # Redis client from the domain's broker; genuinely untyped (optional,
        # un-stubbed adapter dependency reached via a dynamic ``domain`` object).
        self._redis: Any = None
        self._has_subscribers = False
        self._last_subscriber_check = 0.0
        self._initialized = False

        # Stream persistence settings
        self._persist = trace_retention_days > 0
        self._retention_ms = trace_retention_days * 86_400_000

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
        except Exception as e:  # noqa: BLE001 - tracing must never break the engine
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
        except Exception as e:  # noqa: BLE001 - tracing must never break the engine
            logger.debug(f"TraceEmitter: subscriber check failed ({e})")
            self._has_subscribers = False

        return self._has_subscribers

    def emit(
        self,
        event: str,
        stream: str,
        message_id: str,
        message_type: str,
        status: str = "ok",
        handler: str | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        worker_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> None:
        """Emit a trace event. No-op when nobody is listening and persistence is off."""
        has_subscribers = self._check_subscribers()

        # Short-circuit: nothing to do if no subscribers AND persistence is off
        if not has_subscribers and not self._persist:
            return

        # Ensure Redis is available (may not have been initialized yet
        # if persistence is on but _check_subscribers was cached as False)
        if not self._ensure_initialized():
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
                payload=payload,
                worker_id=worker_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            json_str = trace.to_json()

            # Persist to time-bounded Redis Stream for dashboard history
            if self._persist:
                # A retention longer than the epoch would give a negative
                # MINID, which Redis rejects, so trim from 0 (keep everything).
                min_id = str(max(0, int(time.time() * 1000) - self._retention_ms))
                self._redis.xadd(
                    TRACE_STREAM,
                    {"data": json_str},
                    minid=min_id,
                    approximate=True,
                )

            # Broadcast to Pub/Sub for real-time SSE clients
            if has_subscribers:
                self._redis.publish(TRACE_CHANNEL, json_str)
        except Exception as e:  # noqa: BLE001 - tracing must never break the engine
            # Never let tracing failures affect message processing
            logger.debug(f"TraceEmitter publish failed: {e}")
