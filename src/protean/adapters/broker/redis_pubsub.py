import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Dict

import redis

from protean.port.broker import BaseBroker, BrokerCapabilities

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Constants
CONSUMER_GROUP_SEPARATOR = ":"


class RedisPubSubBroker(BaseBroker):
    """Redis as the Message Broker for simple queuing.

    This broker supports basic publish/subscribe with consumer groups
    but does not support ack/nack or advanced message processing.
    """

    __broker__ = "redis_pubsub"

    def __init__(self, name: str, domain: "Domain", conn_info: Dict) -> None:
        super().__init__(name, domain, conn_info)

        self.redis_instance = redis.Redis.from_url(conn_info["URI"])

        # Simple storage for consumer groups
        self._consumer_groups = {}

    @property
    def capabilities(self) -> BrokerCapabilities:
        """Redis PubSub provides simple queuing with manual consumer groups."""
        return BrokerCapabilities.SIMPLE_QUEUING

    def _publish(self, stream: str, message: dict) -> str:
        """Publish a message to Redis list"""
        # Always generate a new identifier
        identifier = str(uuid.uuid4())

        message_tuple = (identifier, message)
        self.redis_instance.rpush(stream, json.dumps(message_tuple))

        return identifier

    def _get_next(self, stream: str, consumer_group: str) -> tuple[str, dict] | None:
        """Get next message in stream for a specific consumer group"""
        # Ensure consumer group exists
        self._ensure_group(consumer_group, stream)

        # Get current position for this consumer group
        position_key = f"position:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        position = int(self.redis_instance.get(position_key) or 0)

        # Get message at this position
        message_data = self.redis_instance.lindex(stream, position)
        if message_data:
            identifier, message = json.loads(message_data)

            # Increment position for this consumer group
            self.redis_instance.incr(position_key)

            return (identifier, message)

        # No message available
        return None

    def _read(
        self, stream: str, consumer_group: str, no_of_messages: int
    ) -> list[tuple[str, dict]]:
        """Read messages from the broker for a specific consumer group"""
        # Ensure consumer group exists
        self._ensure_group(consumer_group, stream)

        messages = []
        for _ in range(no_of_messages):
            message = self._get_next(stream, consumer_group)
            if message:
                messages.append(message)
            else:
                break

        return messages

    def _ack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Acknowledge - not supported in simple queuing"""
        logger.warning(
            f"ACK not supported by {self.__class__.__name__} - message {identifier} cannot be acknowledged"
        )
        return False

    def _nack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Negative acknowledge - not supported in simple queuing"""
        logger.warning(
            f"NACK not supported by {self.__class__.__name__} - message {identifier} cannot be nacked"
        )
        return False

    def _ensure_group(self, group_name: str, stream: str) -> None:
        """Bootstrap/create consumer group"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{group_name}"
        if group_key not in self._consumer_groups:
            self._consumer_groups[group_key] = {
                "consumers": set(),
                "created_at": time.time(),
            }

    def _info(self) -> dict:
        """Provide information about consumer groups"""
        # Group info by consumer group name across all streams
        consumer_groups_info = {}

        for group_key, group_info in self._consumer_groups.items():
            # Extract stream and consumer group name from the combined key
            stream, consumer_group = group_key.split(CONSUMER_GROUP_SEPARATOR, 1)

            if consumer_group not in consumer_groups_info:
                consumer_groups_info[consumer_group] = {
                    "consumers": list(group_info["consumers"]),
                    "created_at": group_info["created_at"],
                    "consumer_count": len(group_info["consumers"]),
                }

        return {"consumer_groups": consumer_groups_info}

    def _ping(self) -> bool:
        """Test basic connectivity to Redis broker"""
        try:
            return self.redis_instance.ping()
        except Exception as e:
            logger.debug(f"Redis PubSub ping failed: {e}")
            return False

    def _health_stats(self) -> dict:
        """Get health statistics for the Redis PubSub broker"""
        try:
            redis_info = self.redis_instance.info()

            # Basic health stats
            stats = {
                "healthy": True,
                "connected_clients": redis_info.get("connected_clients", 0),
                "used_memory": redis_info.get("used_memory", 0),
                "used_memory_human": redis_info.get("used_memory_human", "0B"),
                "keyspace_hits": redis_info.get("keyspace_hits", 0),
                "keyspace_misses": redis_info.get("keyspace_misses", 0),
                "message_counts": self._calculate_message_counts(),
                "consumer_groups": {
                    "count": len(self._consumer_groups),
                    "names": list(self._consumer_groups.keys()),
                },
            }

            # Calculate hit rate
            hits = stats["keyspace_hits"]
            misses = stats["keyspace_misses"]
            if hits + misses > 0:
                stats["hit_rate"] = hits / (hits + misses)
            else:
                stats["hit_rate"] = 0.0

            # Check for potential health issues
            if redis_info.get("loading", 0) == 1:
                stats["healthy"] = False
                stats["warning"] = "Redis is loading data from disk"

            if redis_info.get("rejected_connections", 0) > 0:
                stats["healthy"] = False
                stats["warning"] = "Redis has rejected connections"

            # Add configuration details
            stats["configuration"] = {
                "broker_type": "redis_pubsub",
                "native_consumer_groups": False,
                "native_ack_nack": False,
                "simple_queuing_only": True,
            }

            return stats

        except Exception as e:
            logger.error(f"Error getting Redis PubSub health stats: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "message_counts": {"total_messages": 0},
                "consumer_groups": {"count": 0, "names": []},
                "configuration": {
                    "broker_type": "redis_pubsub",
                    "error": "Failed to get configuration",
                    "simple_queuing_only": True,
                },
            }

    def _calculate_message_counts(self) -> dict:
        """Calculate message counts across all streams"""
        try:
            # Get all streams from subscriber keys
            streams = set(self._subscribers.keys())

            # Get streams from consumer group keys
            for group_key in self._consumer_groups:
                if CONSUMER_GROUP_SEPARATOR in group_key:
                    stream_name = group_key.split(CONSUMER_GROUP_SEPARATOR, 1)[0]
                    streams.add(stream_name)

            total_messages = 0
            for stream in streams:
                try:
                    stream_length = self.redis_instance.llen(stream)
                    total_messages += stream_length
                except redis.ResponseError:
                    # Stream might not exist
                    pass

            return {"total_messages": total_messages}

        except Exception as e:
            logger.debug(f"Error calculating message counts: {e}")
            return {"total_messages": 0}

    def _ensure_connection(self) -> bool:
        """Ensure connection to Redis broker is healthy"""
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                if self.redis_instance.ping():
                    if attempt > 0:
                        logger.info(
                            f"Redis connection restored on attempt {attempt + 1}"
                        )
                    return True
            except Exception as e:
                logger.debug(f"Redis connection attempt {attempt + 1} failed: {e}")

            # Connection failed, try to reconnect
            if attempt < max_attempts - 1:
                try:
                    logger.info(
                        f"Redis connection failed, attempting to reconnect (attempt {attempt + 1}/{max_attempts})..."
                    )
                    self.redis_instance = redis.Redis.from_url(self.conn_info["URI"])
                except Exception as reconnect_error:
                    logger.error(
                        f"Failed to create new Redis connection: {reconnect_error}"
                    )

        logger.error(f"Failed to ensure Redis connection after {max_attempts} attempts")
        return False

    def _data_reset(self) -> None:
        """Flush all data in Redis instance for testing"""
        try:
            self.redis_instance.flushall()
            self._consumer_groups.clear()
        except Exception as e:
            logger.error(f"Error during data reset: {e}")
