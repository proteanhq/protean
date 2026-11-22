"""Reach the Redis client behind a broker, for the server's Redis-only views."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import redis

    from protean.infra.broker import Broker


def redis_client(broker: "Broker | None") -> "redis.Redis[Any] | None":
    """Return the broker's Redis client, or ``None`` if it has none.

    Returns ``None`` for a missing broker, for a broker whose connection is not
    a Redis client, and when the ``redis`` package is not installed. An error
    the broker's ``get_connection()`` raises is not caught.
    """
    if broker is None:
        return None
    try:
        # redis is an optional extra, so it is imported only when a view asks.
        import redis  # noqa: PLC0415
    except ImportError:
        return None
    connection = broker.get_connection()
    if isinstance(connection, redis.Redis):
        return connection
    return None
