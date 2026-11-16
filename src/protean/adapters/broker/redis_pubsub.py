import json
import logging
import time
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import redis

from protean.infra.registry import brokers
from protean.port.broker import (
    BaseBroker,
    BrokerCapabilities,
    BrokerHealth,
    BrokerMessage,
    BrokerPort,
    ConsumerGroupInfo,
    DLQEntry,
)

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Constants
CONSUMER_GROUP_SEPARATOR = ":"


class RedisPubSubBroker(BaseBroker, BrokerPort):
    """Redis as the Message Broker for simple queuing.

    This broker supports basic publish/subscribe with consumer groups
    but does not support ack/nack or advanced message processing.
    """

    __broker__ = "redis_pubsub"

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        super().__init__(name, domain, config)

        self.redis_instance = redis.Redis.from_url(str(self.config["URI"]))

        # Simple storage for consumer groups
        self._consumer_groups: dict[str, dict[str, Any]] = {}

    @property
    def capabilities(self) -> BrokerCapabilities:
        """Redis PubSub provides simple queuing with manual consumer groups."""
        return BrokerCapabilities.SIMPLE_QUEUING

    def publish(self, stream: str, message: dict[str, Any]) -> str:
        """Publish a message to Redis list"""
        # Always generate a new identifier
        identifier = str(uuid.uuid4())

        message_tuple = (identifier, message)
        self.redis_instance.rpush(stream, json.dumps(message_tuple))

        return identifier

    def _next_message(self, stream: str, consumer_group: str) -> BrokerMessage | None:
        """Return the message at the group's position and advance the position."""
        position_key = f"position:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        position = int(self.redis_instance.get(position_key) or 0)

        message_data = self.redis_instance.lindex(stream, position)
        if message_data:
            identifier, message = json.loads(message_data)
            self.redis_instance.incr(position_key)
            return BrokerMessage(identifier, message)

        return None

    def read(
        self,
        stream: str,
        consumer_group: str,
        limit: int,
        *,
        new_messages: bool = False,
    ) -> list[BrokerMessage]:
        """Read up to ``limit`` messages the group has not received yet.

        The broker keeps one read position per group and never redelivers, so
        ``new_messages`` makes no difference here.
        """
        self.create_group(stream, consumer_group)

        messages = []
        for _ in range(limit):
            message = self._next_message(stream, consumer_group)
            if message:
                messages.append(message)
            else:
                break

        return messages

    def ack(self, stream: str, message_id: str, consumer_group: str) -> bool:  # pragma: no cover  # the service returns before this: no ACK_NACK capability  # fmt: skip
        """Acknowledge - not supported in simple queuing"""
        logger.warning(
            f"ACK not supported by {self.__class__.__name__} - message {message_id} cannot be acknowledged"
        )
        return False

    def nack(self, stream: str, message_id: str, consumer_group: str) -> bool:  # pragma: no cover  # the service returns before this: no ACK_NACK capability  # fmt: skip
        """Negative acknowledge - not supported in simple queuing"""
        logger.warning(
            f"NACK not supported by {self.__class__.__name__} - message {message_id} cannot be nacked"
        )
        return False

    def create_group(self, stream: str, consumer_group: str) -> None:
        """Create ``consumer_group`` on ``stream`` if it does not exist."""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        if group_key not in self._consumer_groups:
            self._consumer_groups[group_key] = {
                "consumers": set(),
                "created_at": time.time(),
            }

    def consumer_groups(self) -> dict[str, ConsumerGroupInfo]:
        """Return each consumer group by name, across all streams.

        The broker has no acknowledgement, so ``pending`` is always ``0``.
        """
        consumer_groups_info: dict[str, ConsumerGroupInfo] = {}

        for group_key, group_info in self._consumer_groups.items():
            _stream, consumer_group = group_key.rsplit(CONSUMER_GROUP_SEPARATOR, 1)

            if consumer_group not in consumer_groups_info:
                consumer_groups_info[consumer_group] = {
                    "name": consumer_group,
                    "consumer_count": len(group_info["consumers"]),
                    "pending": 0,
                    "consumers": [
                        {"name": consumer, "pending": 0}
                        for consumer in group_info["consumers"]
                    ],
                    "created_at": group_info["created_at"],
                }

        return consumer_groups_info

    def ping(self) -> bool:
        """Test basic connectivity to Redis broker"""
        try:
            return self.redis_instance.ping()
        # ping() raises a plain ValueError for a malformed reply.
        except (redis.RedisError, OSError, ValueError) as e:
            logger.debug(f"Redis PubSub ping failed: {e}")
            return False

    def health(self) -> BrokerHealth:
        """Return message counts, consumer groups and Redis server statistics.

        A failure while reading the statistics is reported as unhealthy and
        not raised.
        """
        try:
            redis_info = self.redis_instance.info()

            details: dict[str, Any] = {
                "connected_clients": redis_info.get("connected_clients", 0),
                "used_memory": redis_info.get("used_memory", 0),
                "used_memory_human": redis_info.get("used_memory_human", "0B"),
                "keyspace_hits": redis_info.get("keyspace_hits", 0),
                "keyspace_misses": redis_info.get("keyspace_misses", 0),
            }
            healthy = True

            # Calculate hit rate
            hits = details["keyspace_hits"]
            misses = details["keyspace_misses"]
            if hits + misses > 0:
                details["hit_rate"] = hits / (hits + misses)
            else:
                details["hit_rate"] = 0.0

            # Check for potential health issues
            if redis_info.get("loading", 0) == 1:
                healthy = False
                details["warning"] = "Redis is loading data from disk"

            if redis_info.get("rejected_connections", 0) > 0:
                healthy = False
                details["warning"] = "Redis has rejected connections"

            # Add configuration details
            details["configuration"] = {
                "broker_type": "redis_pubsub",
                "native_consumer_groups": False,
                "native_ack_nack": False,
                "simple_queuing_only": True,
            }

            return BrokerHealth(
                healthy=healthy,
                message_counts=self._calculate_message_counts(),
                consumer_groups={
                    "count": len(self._consumer_groups),
                    "names": list(self._consumer_groups.keys()),
                },
                details=details,
            )

        # a health check reports failure instead of raising; logged
        except Exception as e:
            logger.exception("broker.redis_pubsub.health_check_failed")
            return BrokerHealth(
                healthy=False,
                message_counts={"total_messages": 0},
                consumer_groups={"count": 0, "names": []},
                details={
                    "error": str(e),
                    "configuration": {
                        "broker_type": "redis_pubsub",
                        "error": "Failed to get configuration",
                        "simple_queuing_only": True,
                    },
                },
            )

    def _calculate_message_counts(self) -> dict[str, int]:
        """Calculate message counts across all streams"""
        try:
            streams: set[str] = set()
            for group_key in self._consumer_groups:
                if CONSUMER_GROUP_SEPARATOR in group_key:
                    stream_name = group_key.rsplit(CONSUMER_GROUP_SEPARATOR, 1)[0]
                    streams.add(stream_name)

            total_messages = 0
            for stream in streams:
                # TYPE answers "none" for a missing key; skip anything not a list.
                # redis-stubs leaves type untyped (stub gap).
                key_type = self.redis_instance.type(stream)  # type: ignore[no-untyped-call]
                if key_type not in (b"list", "list"):
                    continue
                total_messages += self.redis_instance.llen(stream)

            return {"total_messages": total_messages}

        except redis.RedisError as e:
            logger.debug(f"Error calculating message counts: {e}")
            return {"total_messages": 0}

    def reconnect(self) -> bool:
        """Check the connection to Redis and reconnect if it is broken."""
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                if self.redis_instance.ping():
                    if attempt > 0:
                        logger.info(
                            f"Redis connection restored on attempt {attempt + 1}"
                        )
                    return True
            # ping() raises a plain ValueError for a malformed reply.
            except (redis.RedisError, OSError, ValueError) as e:
                logger.debug(f"Redis connection attempt {attempt + 1} failed: {e}")

            # Connection failed, try to reconnect
            if attempt < max_attempts - 1:
                try:
                    logger.info(
                        f"Redis connection failed, attempting to reconnect (attempt {attempt + 1}/{max_attempts})..."
                    )
                    # from_url() does not connect; it raises ValueError for a bad URI.
                    self.redis_instance = redis.Redis.from_url(str(self.config["URI"]))
                except ValueError as reconnect_error:
                    logger.error(
                        f"Failed to create new Redis connection: {reconnect_error}"
                    )

        logger.error(f"Failed to ensure Redis connection after {max_attempts} attempts")
        return False

    def get_connection(self) -> "redis.Redis[Any]":
        """Return the Redis client."""
        return self.redis_instance

    def clear(self) -> None:
        """Clear the broker's configured Redis database for testing"""
        try:
            self.redis_instance.flushdb()
            self._consumer_groups.clear()
        except Exception:  # a failed test reset is logged, not raised
            logger.exception("broker.redis_pubsub.data_reset_failed")

    # DLQ methods — not supported by PubSub broker (no DEAD_LETTER_QUEUE capability).
    # These stubs satisfy the abstract interface; the capability gate in BaseBroker
    # prevents them from ever being called.

    def _dlq_list(self, dlq_streams: list[str], limit: int = 100) -> list[DLQEntry]:
        return []

    def _dlq_inspect(self, dlq_stream: str, dlq_id: str) -> DLQEntry | None:
        return None

    def _dlq_replay(self, dlq_stream: str, dlq_id: str, target_stream: str) -> bool:
        return False

    def _dlq_replay_all(self, dlq_stream: str, target_stream: str) -> int:
        return 0

    def _dlq_purge(self, dlq_stream: str) -> int:
        return 0


# Self-registration function for entry point
def register() -> None:
    """Register Redis PubSub broker with Protean if redis is available."""
    try:
        import redis  # noqa: F401, PLC0415

        brokers.register(
            "redis_pubsub", "protean.adapters.broker.redis_pubsub.RedisPubSubBroker"
        )
        logger.debug("Redis PubSub broker registered successfully")
    except ImportError as e:
        # Redis not available, skip registration
        logger.debug(
            f"Redis PubSub broker not registered: redis package not available ({e})"
        )


_PORT_CHECK: type[BrokerPort] = RedisPubSubBroker
