import json
import logging
import time
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import redis

from protean.port.broker import BaseBroker

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Constants
DATA_FIELD = "data"
STREAM_ID_START = "0"
CONSUMER_GROUP_SEPARATOR = ":"
NEW_MESSAGES_ID = ">"


class RedisBroker(BaseBroker):
    """Redis Streams as the Message Broker.

    This broker leverages Redis Streams' native consumer group functionality
    with built-in ack/nack support, providing true message queue semantics.
    """

    __broker__ = "redis"

    def __init__(self, name: str, domain: "Domain", conn_info: Dict) -> None:
        super().__init__(name, domain, conn_info)

        self.redis_instance = redis.Redis.from_url(conn_info["URI"])
        self._consumer_name = f"consumer-{int(time.time() * 1000)}"
        self._created_groups = set()
        self._nacked_messages = set()
        self._group_creation_times = {}  # Track creation times for consistency

    def _publish(self, stream: str, message: dict) -> str:
        """Publish a message to Redis Stream using XADD"""
        serialized_message = {DATA_FIELD: json.dumps(message or {})}
        redis_stream_id = self.redis_instance.xadd(stream, serialized_message)
        return self._decode_if_bytes(redis_stream_id)

    def _get_next(self, stream: str, consumer_group: str) -> Optional[Tuple[str, dict]]:
        """Get next message from Redis Stream using consumer group"""
        self._ensure_group(consumer_group, stream)

        try:
            response = self.redis_instance.xreadgroup(
                consumer_group, self._consumer_name, {stream: NEW_MESSAGES_ID}, count=1
            )

            return self._extract_message_from_response(response)

        except redis.ResponseError as e:
            return self._handle_redis_error(e, stream, consumer_group)
        except Exception as e:
            logger.error(f"Unexpected error in _get_next: {e}")
            return None

    def _extract_message_from_response(self, response) -> Optional[Tuple[str, dict]]:
        """Extract message from Redis response"""
        if not (response and response[0][1]):
            return None

        _, messages = response[0]
        if not messages:
            return None

        message_id, fields = messages[0]
        redis_id_str = self._decode_if_bytes(message_id)
        message = self._deserialize_message(fields)
        return (redis_id_str, message)

    def _handle_redis_error(
        self, error: redis.ResponseError, stream: str, consumer_group: str
    ) -> Optional[Tuple[str, dict]]:
        """Handle Redis errors during message retrieval"""
        if "NOGROUP" in str(error):
            self._ensure_group(consumer_group, stream)
            return self._get_next(stream, consumer_group)

        logger.debug(f"Redis error in _get_next: {error}")
        return None

    def _deserialize_message(self, fields: dict) -> dict:
        """Deserialize the message from the fields"""
        data_field = self._extract_data_field(fields)
        if data_field is None:
            return {}

        try:
            data_str = self._decode_if_bytes(data_field)
            return json.loads(data_str)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to deserialize message: {e}")
            return {}

    def _extract_data_field(self, fields: dict):
        """Extract the data field from Redis fields"""
        for key, value in fields.items():
            key_str = self._decode_if_bytes(key)
            if key_str == DATA_FIELD:
                return value
        return None

    def _decode_if_bytes(self, value) -> str:
        """Convert bytes to string if needed, otherwise return as string"""
        if isinstance(value, bytes):
            return value.decode()
        return str(value)

    def read(
        self, stream: str, consumer_group: str, no_of_messages: int
    ) -> List[Tuple[str, dict]]:
        """Read multiple messages from Redis Stream"""
        messages = []
        for _ in range(no_of_messages):
            message = self._get_next(stream, consumer_group)
            if message:
                messages.append(message)
            else:
                break
        return messages

    def ack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Acknowledge message using Redis Streams XACK"""
        nack_key = self._get_nack_key(stream, consumer_group, identifier)
        if nack_key in self._nacked_messages:
            logger.debug(f"Cannot ACK message {identifier} - it was previously NACKed")
            return False

        try:
            result = self.redis_instance.xack(stream, consumer_group, identifier)
            return bool(result)
        except redis.ResponseError as e:
            logger.warning(f"Failed to ack message {identifier} in {stream}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during ack: {e}")
            return False

    def nack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Negative acknowledge - return message to pending list for reprocessing"""
        try:
            # Ensure the consumer group exists first
            self._ensure_group(consumer_group, stream)

            if not self._is_message_pending(stream, consumer_group, identifier):
                return False

            # Track the NACKed message to prevent ACKing it later
            nack_key = self._get_nack_key(stream, consumer_group, identifier)
            self._nacked_messages.add(nack_key)
            logger.debug(
                f"Message {identifier} in {stream} marked for reprocessing (remains pending)"
            )
            return True

        except Exception as e:
            logger.error(f"Unexpected error during nack: {e}")
            return False

    def _is_message_pending(
        self, stream: str, consumer_group: str, identifier: str
    ) -> bool:
        """Check if message is in pending list for the consumer group"""
        try:
            pending_info = self.redis_instance.xpending_range(
                stream, consumer_group, min=identifier, max=identifier, count=1
            )
        except redis.ResponseError as e:
            logger.debug(f"Redis error during XPENDING: {e}")
            return False

        if not pending_info:
            logger.debug(
                f"Message {identifier} not found in pending list for {consumer_group}"
            )
            return False

        # Validate message info
        message_info = pending_info[0]
        message_id = self._decode_if_bytes(message_info["message_id"])

        if message_id != identifier:
            logger.debug(
                f"Message ID mismatch: expected {identifier}, got {message_id}"
            )
            return False

        return True

    def _get_nack_key(self, stream: str, consumer_group: str, identifier: str) -> str:
        """Generate key for tracking NACKed messages"""
        return f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}{CONSUMER_GROUP_SEPARATOR}{identifier}"

    def _ensure_group(self, group_name: str, stream: str) -> None:
        """Create consumer group if it doesn't exist"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{group_name}"

        if group_key in self._created_groups:
            return

        try:
            self.redis_instance.xgroup_create(
                stream, group_name, id=STREAM_ID_START, mkstream=True
            )
            logger.debug(f"Created consumer group {group_name} for stream {stream}")
            self._created_groups.add(group_key)
            # Track creation time for consistency
            if group_name not in self._group_creation_times:
                self._group_creation_times[group_name] = time.time()
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                self._created_groups.add(group_key)
                # Track creation time for existing groups too
                if group_name not in self._group_creation_times:
                    self._group_creation_times[group_name] = time.time()
            else:
                logger.warning(
                    f"Failed to create consumer group {group_name} for stream {stream}: {e}"
                )
        except Exception as e:
            logger.error(
                f"Error ensuring consumer group {group_name} for stream {stream}: {e}"
            )

    def _info(self) -> dict:
        """Get information about consumer groups and consumers"""
        info = {"consumer_groups": {}}
        stream_info_nested = {}  # For Redis-specific structure

        try:
            streams_to_check = self._get_streams_to_check()

            for stream in streams_to_check:
                stream_info = self._get_stream_info(stream)
                if stream_info:
                    # Store nested structure for Redis-specific access
                    stream_info_nested[stream] = stream_info

                    # Flatten the structure to match inline broker format
                    for group_name, group_details in stream_info.items():
                        # Add created_at and consumer_count for compatibility
                        group_details["created_at"] = self._group_creation_times.get(
                            group_name, time.time()
                        )
                        group_details["consumer_count"] = len(
                            group_details["consumers"]
                        )
                        info["consumer_groups"][group_name] = group_details

            # Add nested structure for Redis-specific tests
            info["consumer_groups"].update(stream_info_nested)

        except Exception as e:
            logger.error(f"Error getting broker info: {e}")

        return info

    def _get_streams_to_check(self) -> set:
        """Get set of streams to check for info"""
        streams = set(self._subscribers.keys())

        # Add streams from created consumer groups
        for group_key in self._created_groups:
            if CONSUMER_GROUP_SEPARATOR in group_key:
                stream_name = group_key.split(CONSUMER_GROUP_SEPARATOR, 1)[0]
                streams.add(stream_name)

        return streams

    def _get_stream_info(self, stream: str) -> Optional[dict]:
        """Get info for a specific stream"""
        try:
            groups_info = self.redis_instance.xinfo_groups(stream)
            stream_info = {}

            for group_info in groups_info:
                if not isinstance(group_info, dict):
                    continue

                group_data = self._extract_group_data(group_info, stream)
                if group_data:
                    group_name, group_details = group_data
                    stream_info[group_name] = group_details

            return stream_info if stream_info else None

        except redis.ResponseError:
            # Stream might not exist
            return None

    def _extract_group_data(
        self, group_info: dict, stream: str
    ) -> Optional[Tuple[str, dict]]:
        """Extract group data from Redis group info"""
        try:
            # Handle both bytes and string keys
            group_name = self._get_field_value(group_info, "name")
            pending_count = self._get_field_value(
                group_info, "pending", convert_to_int=True
            )
            last_delivered_id = self._get_field_value(group_info, "last-delivered-id")

            if group_name is None:
                return None

            consumers_info = self.redis_instance.xinfo_consumers(stream, group_name)
            consumers = self._extract_consumers_data(consumers_info)

            return (
                group_name,
                {
                    "consumers": consumers,
                    "pending": pending_count,
                    "last_delivered_id": last_delivered_id,
                },
            )

        except Exception as e:
            logger.debug(f"Error extracting group data: {e}")
            return None

    def _extract_consumers_data(self, consumers_info) -> List[dict]:
        """Extract consumers data from Redis consumer info"""
        consumers = []
        for consumer_info in consumers_info:
            if not isinstance(consumer_info, dict):
                continue

            consumer_name = self._get_field_value(consumer_info, "name")
            consumer_pending = self._get_field_value(
                consumer_info, "pending", convert_to_int=True
            )

            if consumer_name is not None:
                consumers.append({"name": consumer_name, "pending": consumer_pending})

        return consumers

    def _get_field_value(
        self, info_dict: dict, field_name: str, convert_to_int: bool = False
    ):
        """Get field value from Redis info dict, handling both bytes and string keys"""
        for key_format in [field_name.encode(), field_name]:
            if key_format in info_dict:
                value = info_dict[key_format]
                decoded_value = self._decode_if_bytes(value)

                if convert_to_int:
                    try:
                        return int(decoded_value)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Failed to convert {decoded_value} to int for field {field_name}"
                        )
                        return 0

                return decoded_value
        return None

    def _data_reset(self) -> None:
        """Flush all data in Redis instance for testing"""
        try:
            self.redis_instance.flushall()
            self._created_groups.clear()
            self._nacked_messages.clear()
            self._group_creation_times.clear()
        except Exception as e:
            logger.error(f"Error during data reset: {e}")
