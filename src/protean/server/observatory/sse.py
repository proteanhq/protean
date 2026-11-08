"""Server-Sent Events (SSE) endpoint for real-time message trace streaming.

Subscribes to Redis Pub/Sub channel 'protean:trace' and streams MessageTrace
events to connected clients. Supports server-side filtering by domain, stream,
event type, and message type.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from fnmatch import fnmatch
from typing import (
    Any,
    Protocol,
    cast,
)

from fastapi import Query, Request
from fastapi.responses import StreamingResponse

from protean.domain import Domain

from ..tracing import TRACE_CHANNEL, decode_trace_payload

logger = logging.getLogger(__name__)


class _RedisStyleBroker(Protocol):
    """Structural view of the Redis-backed broker surface used for SSE streaming.

    The concrete Redis broker adapters expose ``redis_instance`` (the live
    ``redis.Redis`` client), which is not part of the ``BaseBroker`` port. The
    guarded ``hasattr`` check at the call site narrows a ``BaseBroker`` to this
    shape. ``redis_instance`` is typed ``Any`` because the ``redis`` client is an
    optional dependency not importable at module scope here.
    """

    redis_instance: Any


def create_sse_endpoint(
    domains: list[Domain],
) -> Callable[..., Awaitable[StreamingResponse]]:
    """Create the SSE streaming endpoint function.

    Args:
        domains: List of Protean domains to monitor.
    """

    async def stream_events(
        request: Request,
        domain: str | None = Query(None, description="Filter by domain name"),
        stream: str | None = Query(None, description="Filter by stream category"),
        event: str | None = Query(
            None, description="Filter by event type (supports glob: handler.*)"
        ),
        type: str | None = Query(
            None, description="Filter by message type (supports glob)"
        ),
    ) -> StreamingResponse:
        """Stream real-time MessageTrace events via Server-Sent Events."""
        return StreamingResponse(
            _trace_event_stream(
                request,
                domains,
                domain=domain,
                stream=stream,
                event=event,
                message_type=type,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return stream_events


async def _trace_event_stream(
    request: Request,
    domains: list[Domain],
    *,
    domain: str | None,
    stream: str | None,
    event: str | None,
    message_type: str | None,
) -> AsyncIterator[str]:
    """Yield SSE chunks for the traces on the trace channel that pass the filters.

    Yields one error event and stops when no domain has a Redis broker.
    Between messages it yields keepalive comments, and it stops when the
    client disconnects.
    """
    redis_conn = _first_redis_connection(domains)

    if not redis_conn:
        yield _format_sse({"error": "Redis not available"}, event_type="error")
        return

    # Create a dedicated pub/sub subscriber
    pubsub = redis_conn.pubsub()
    try:
        pubsub.subscribe(TRACE_CHANNEL)

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            # Offload synchronous Redis pubsub to thread pool
            # to avoid blocking the async event loop
            message = await asyncio.to_thread(
                pubsub.get_message,
                ignore_subscribe_messages=True,
                timeout=1.0,
            )

            chunk = _sse_chunk(message, domain, stream, event, message_type)
            # A trace that fails to decode or is filtered out yields nothing,
            # and the loop polls again at once.
            if chunk is None:
                continue
            yield chunk

            # Yield control to event loop
            await asyncio.sleep(0.01)

    finally:
        pubsub.unsubscribe(TRACE_CHANNEL)
        pubsub.close()


def _first_redis_connection(domains: list[Domain]) -> Any:
    """Return the Redis client of the first domain whose default broker has one, or ``None``."""
    for d in domains:
        try:
            with d.domain_context():
                broker = d.brokers.get("default")
                if broker and hasattr(broker, "redis_instance"):
                    return cast(_RedisStyleBroker, broker).redis_instance
        except Exception:  # one broken domain must not stop the stream; logged
            logger.debug(
                "Could not get the Redis broker of domain %s",
                d.name,
                exc_info=True,
            )
            continue
    return None


def _sse_chunk(
    message: Any,
    domain: str | None,
    stream: str | None,
    event: str | None,
    message_type: str | None,
) -> str | None:
    """Return the SSE chunk for one pub/sub poll result.

    A trace message becomes a trace event, or ``None`` when it fails to decode
    or a filter rejects it. An empty poll becomes a keepalive comment.
    """
    if message and message["type"] == "message":
        data = decode_trace_payload(message["data"])
        if data is None or not _passes_filters(
            data, domain, stream, event, message_type
        ):
            return None
        return _format_sse(data)

    # No message, yield a keepalive comment to prevent timeouts
    return ": keepalive\n\n"


def _passes_filters(
    data: dict[str, Any],
    domain: str | None,
    stream: str | None,
    event: str | None,
    message_type: str | None,
) -> bool:
    """Return whether a decoded trace passes every filter that is set."""
    if domain and data.get("domain") != domain:
        return False
    if stream and data.get("stream") != stream:
        return False
    if event and not _matches(data.get("event", ""), event):
        return False
    return not message_type or _matches(data.get("message_type", ""), message_type)


def _matches(value: object, pattern: str) -> bool:
    """Match a trace value against a glob pattern. A non-str value never matches."""
    return isinstance(value, str) and fnmatch(value, pattern)


def _format_sse(data: dict[str, Any], event_type: str = "trace") -> str:
    """Format a dict as an SSE event string."""
    json_str = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {json_str}\n\n"
