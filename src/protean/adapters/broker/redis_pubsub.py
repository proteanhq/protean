import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Dict

import redis

from protean.port.broker import BaseManualBroker, OperationState

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Constants
CONSUMER_GROUP_SEPARATOR = ":"


class RedisPubSubBroker(BaseManualBroker):
    """Redis as the Message Broker.

    FIXME: Convert to be a Context Manager, and release connection after use
    """

    __broker__ = "redis_pubsub"

    def __init__(self, name: str, domain: "Domain", conn_info: Dict) -> None:
        super().__init__(name, domain, conn_info)

        self.redis_instance = redis.Redis.from_url(conn_info["URI"])

    def _publish(self, stream: str, message: dict) -> str:
        # Always generate a new identifier
        identifier = str(uuid.uuid4())

        message_tuple = (identifier, message)
        self.redis_instance.rpush(stream, json.dumps(message_tuple))

        return identifier

    def _get_next(self, stream: str, consumer_group: str) -> tuple[str, dict] | None:
        """Get next message in stream for a specific consumer group"""
        # Ensure consumer group exists (create if it doesn't)
        self._ensure_group(consumer_group, stream)

        # Clean up stale in-flight messages first
        self._cleanup_stale_messages(consumer_group, self._message_timeout)

        # First, check for any failed messages that are ready for retry
        self._requeue_failed_messages(stream, consumer_group)

        # Get current position for this consumer group
        position_key = f"position:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        position = int(self.redis_instance.get(position_key) or 0)

        # Get message at this position
        message_data = self.redis_instance.lindex(stream, position)
        if message_data:
            identifier, message = json.loads(message_data)

            # Use Redis transaction for atomic operation
            pipe = self.redis_instance.pipeline()
            try:
                # Watch the position key for changes
                pipe.watch(position_key)

                # Start transaction
                pipe.multi()

                # Increment position for this consumer group
                pipe.incr(position_key)

                # Track message ownership with reasonable expiration to avoid premature cleanup
                # Use a minimum of 30 seconds to handle fast tests, but scale with message timeout for production
                ownership_key = f"ownership:{identifier}"
                pipe.sadd(
                    ownership_key, f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
                )
                ownership_expiration = max(
                    int(self._message_timeout * 2), 30
                )  # At least 30 seconds
                pipe.expire(ownership_key, ownership_expiration)

                # Clear any previous operation state for fresh processing
                self._clear_operation_state(consumer_group, identifier)

                # Store message in in-flight status
                self._store_in_flight_message(
                    stream, consumer_group, identifier, message
                )

                # Execute transaction
                pipe.execute()

                return (identifier, message)

            except redis.WatchError:
                # Another process modified the position, retry
                logger.debug(
                    f"Position changed during get_next for {consumer_group}:{stream}, retrying"
                )
                return self._get_next(stream, consumer_group)
            except Exception as e:
                logger.error(f"Error in get_next for {consumer_group}:{stream}: {e}")
                return None

        # There is no message in the stream for this consumer group
        return None

    def _read(
        self, stream: str, consumer_group: str, no_of_messages: int
    ) -> list[tuple[str, dict]]:
        """Read messages from the broker for a specific consumer group. Returns tuples of (identifier, message)."""
        # Ensure consumer group exists
        self._ensure_group(consumer_group, stream)

        messages = []
        for _ in range(no_of_messages):
            message = self._get_next(stream, consumer_group)
            if message:
                messages.append(message)
            else:
                # There are no more messages in the stream
                break

        return messages

    ####################################################
    # BaseManualBroker abstract method implementations #
    ####################################################
    def _store_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str, message: dict
    ) -> None:
        """Store a message in in-flight status using Redis hash"""
        in_flight_key = f"in_flight:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        message_info = {
            "identifier": identifier,
            "message": json.dumps(message),
            "timestamp": str(time.time()),
        }
        self.redis_instance.hset(in_flight_key, identifier, json.dumps(message_info))

    def _remove_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove a message from in-flight status"""
        in_flight_key = f"in_flight:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self.redis_instance.hdel(in_flight_key, identifier)

    def _is_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> bool:
        """Check if a message is in in-flight status"""
        in_flight_key = f"in_flight:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        return self.redis_instance.hexists(in_flight_key, identifier)

    def _get_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> tuple[str, dict] | None:
        """Get in-flight message data"""
        in_flight_key = f"in_flight:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        message_data_json = self.redis_instance.hget(in_flight_key, identifier)

        if message_data_json:
            message_data = json.loads(message_data_json)
            message = json.loads(message_data["message"])
            return (identifier, message)
        return None

    def _store_operation_state(
        self, consumer_group: str, identifier: str, state: OperationState
    ) -> None:
        """Store operation state for idempotency"""
        op_state_key = f"op_state:{consumer_group}:{identifier}"
        self.redis_instance.setex(op_state_key, self._operation_state_ttl, state.value)

    def _get_operation_state(
        self, consumer_group: str, identifier: str
    ) -> OperationState | None:
        """Get current operation state"""
        op_state_key = f"op_state:{consumer_group}:{identifier}"
        current_state = self.redis_instance.get(op_state_key)
        if current_state:
            state_value = (
                current_state.decode()
                if isinstance(current_state, bytes)
                else current_state
            )
            for state in OperationState:
                if state.value == state_value:
                    return state
        return None

    def _clear_operation_state(self, consumer_group: str, identifier: str) -> None:
        """Clear operation state"""
        op_state_key = f"op_state:{consumer_group}:{identifier}"
        self.redis_instance.delete(op_state_key)

    def _store_failed_message(
        self,
        stream: str,
        consumer_group: str,
        identifier: str,
        message: dict,
        retry_count: int,
        next_retry_time: float,
    ) -> None:
        """Store a failed message for retry"""
        failed_key = f"failed:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        failed_message_data = {
            "identifier": identifier,
            "message": json.dumps(message),
            "retry_count": retry_count,
            "next_retry_time": str(next_retry_time),
        }
        self.redis_instance.rpush(failed_key, json.dumps(failed_message_data))

    def _remove_failed_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove a failed message from retry queue"""
        try:
            failed_key = f"failed:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            failed_messages = self.redis_instance.lrange(failed_key, 0, -1)

            # Find and remove the message with matching identifier
            for msg_bytes in failed_messages:
                failed_data = json.loads(
                    msg_bytes.decode() if isinstance(msg_bytes, bytes) else msg_bytes
                )
                if failed_data["identifier"] == identifier:
                    # Use lrem to remove the first occurrence
                    self.redis_instance.lrem(failed_key, 1, msg_bytes)
                    break
        except Exception as e:
            logger.debug(f"Error removing failed message '{identifier}': {e}")

    def _get_retry_ready_messages(
        self, stream: str, consumer_group: str
    ) -> list[tuple[str, dict]]:
        """Get messages ready for retry and remove them from failed queue"""
        failed_key = f"failed:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        current_time = time.time()

        try:
            # Get all failed messages
            failed_messages = self.redis_instance.lrange(failed_key, 0, -1)

            # Process each failed message
            ready_for_retry = []
            remaining_failed = []

            for msg_bytes in failed_messages:
                failed_data = json.loads(
                    msg_bytes.decode() if isinstance(msg_bytes, bytes) else msg_bytes
                )
                next_retry_time = float(failed_data["next_retry_time"])

                if next_retry_time <= current_time:
                    # Ready for retry
                    identifier = failed_data["identifier"]
                    message = json.loads(failed_data["message"])
                    ready_for_retry.append((identifier, message))
                else:
                    # Not ready yet
                    remaining_failed.append(msg_bytes)

            # Clear the failed messages list
            self.redis_instance.delete(failed_key)

            # Add back the messages that aren't ready for retry
            if remaining_failed:
                self.redis_instance.rpush(failed_key, *remaining_failed)

            return ready_for_retry
        except Exception as e:
            logger.error(
                f"Error getting retry ready messages for {consumer_group}:{stream}: {e}"
            )
            return []

    def _store_dlq_message(
        self,
        stream: str,
        consumer_group: str,
        identifier: str,
        message: dict,
        failure_reason: str,
    ) -> None:
        """Store a message in Dead Letter Queue"""
        dlq_key = f"dlq:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        dlq_message_data = {
            "identifier": identifier,
            "message": json.dumps(message),
            "failure_reason": failure_reason,
            "timestamp": str(time.time()),
        }
        self.redis_instance.rpush(dlq_key, json.dumps(dlq_message_data))

    def _validate_consumer_group(self, consumer_group: str) -> bool:
        """Validate that the consumer group exists"""
        # For redis_pubsub broker, we need to check all streams for this consumer group
        group_pattern = f"consumer_group:*{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        matching_keys = self.redis_instance.keys(group_pattern)
        return len(matching_keys) > 0

    def _validate_message_ownership(self, identifier: str, consumer_group: str) -> bool:
        """Validate that the message was delivered to the specified consumer group"""
        try:
            ownership_key = f"ownership:{identifier}"
            # Check if any stream+consumer_group combination matches this consumer group
            members = self.redis_instance.smembers(ownership_key)
            for member in members:
                member_str = member.decode() if isinstance(member, bytes) else member
                if member_str.endswith(f"{CONSUMER_GROUP_SEPARATOR}{consumer_group}"):
                    return True
            return False
        except Exception:
            return False

    def _cleanup_stale_messages(
        self, consumer_group: str, timeout_seconds: float
    ) -> None:
        """Remove messages that have been in-flight too long"""
        try:
            current_time = time.time()
            cutoff_time = current_time - timeout_seconds

            # Find all in-flight keys for this consumer group
            in_flight_pattern = f"in_flight:*{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            in_flight_keys = self.redis_instance.keys(in_flight_pattern)

            for in_flight_key in in_flight_keys:
                if isinstance(in_flight_key, bytes):
                    in_flight_key = in_flight_key.decode("utf-8")

                # Extract stream name from key
                stream = in_flight_key.replace("in_flight:", "").split(
                    CONSUMER_GROUP_SEPARATOR
                )[0]

                # Get all in-flight messages for this stream
                in_flight_messages = self.redis_instance.hgetall(in_flight_key)

                for identifier_bytes, message_data_bytes in in_flight_messages.items():
                    identifier = (
                        identifier_bytes.decode()
                        if isinstance(identifier_bytes, bytes)
                        else identifier_bytes
                    )
                    message_data_json = (
                        message_data_bytes.decode()
                        if isinstance(message_data_bytes, bytes)
                        else message_data_bytes
                    )

                    try:
                        message_data = json.loads(message_data_json)
                        timestamp = float(message_data["timestamp"])

                        if timestamp < cutoff_time:
                            message = json.loads(message_data["message"])

                            # Use transaction to move to DLQ and clean up
                            pipe = self.redis_instance.pipeline()

                            # Remove from in-flight
                            pipe.hdel(in_flight_key, identifier)

                            # Move to DLQ if enabled
                            if self._enable_dlq:
                                self._store_dlq_message(
                                    stream,
                                    consumer_group,
                                    identifier,
                                    message,
                                    "timeout",
                                )
                                logger.warning(
                                    f"Message '{identifier}' moved to DLQ due to timeout"
                                )

                            # Clean up tracking
                            self._remove_retry_count(stream, consumer_group, identifier)
                            self._cleanup_message_ownership(identifier, consumer_group)

                            pipe.execute()

                    except Exception as e:
                        logger.error(
                            f"Error processing stale message '{identifier}': {e}"
                        )

        except Exception as e:
            logger.error(
                f"Error cleaning up stale messages for consumer group '{consumer_group}': {e}"
            )

    def _get_retry_count(
        self, stream: str, consumer_group: str, identifier: str
    ) -> int:
        """Get current retry count for a message"""
        try:
            retry_key = (
                f"retry_count:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            )
            count = self.redis_instance.hget(retry_key, identifier)
            return int(count) if count else 0
        except Exception:
            return 0

    def _set_retry_count(
        self, stream: str, consumer_group: str, identifier: str, count: int
    ) -> None:
        """Set retry count for a message"""
        retry_key = f"retry_count:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self.redis_instance.hset(retry_key, identifier, count)

    def _remove_retry_count(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove retry count tracking for a message"""
        retry_key = f"retry_count:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self.redis_instance.hdel(retry_key, identifier)

    def _requeue_messages(
        self, stream: str, consumer_group: str, messages: list[tuple[str, dict]]
    ) -> None:
        """Requeue messages back to the main queue"""
        if not messages:
            return

        try:
            # Get current consumer position
            position_key = (
                f"position:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            )
            current_position = int(self.redis_instance.get(position_key) or 0)

            # Insert messages at the current position using a more complex approach
            # Since Redis doesn't have list insert-at-index, we need to work around this
            for identifier, message in reversed(messages):
                message_json = json.dumps((identifier, message))

                if current_position == 0:
                    # Insert at the beginning
                    self.redis_instance.lpush(stream, message_json)
                else:
                    # For positions > 0, we need to get all elements, modify the list, and rebuild
                    # This is not efficient but necessary for test compatibility
                    all_messages = self.redis_instance.lrange(stream, 0, -1)
                    all_messages.insert(
                        current_position,
                        message_json.encode()
                        if isinstance(message_json, str)
                        else message_json,
                    )

                    # Clear and rebuild the list
                    self.redis_instance.delete(stream)
                    if all_messages:
                        self.redis_instance.rpush(stream, *all_messages)

            # Update all consumer positions that are at or beyond this position
            position_pattern = f"position:{stream}{CONSUMER_GROUP_SEPARATOR}*"
            position_keys = self.redis_instance.keys(position_pattern)
            for pos_key in position_keys:
                if isinstance(pos_key, bytes):
                    pos_key = pos_key.decode("utf-8")

                # Don't update the current consumer group's position
                if pos_key != position_key:
                    pos_value = int(self.redis_instance.get(pos_key) or 0)
                    if pos_value >= current_position:
                        self.redis_instance.set(pos_key, pos_value + len(messages))

        except Exception as e:
            logger.error(f"Error requeuing messages for {consumer_group}:{stream}: {e}")

    def _cleanup_message_ownership(self, identifier: str, consumer_group: str) -> None:
        """Clean up message ownership tracking"""
        try:
            ownership_key = f"ownership:{identifier}"
            pipe = self.redis_instance.pipeline()

            # Remove all stream+consumer_group combinations for this consumer group
            members = self.redis_instance.smembers(ownership_key)
            for member in members:
                member_str = member.decode() if isinstance(member, bytes) else member
                if member_str.endswith(f"{CONSUMER_GROUP_SEPARATOR}{consumer_group}"):
                    pipe.srem(ownership_key, member)

            pipe.scard(ownership_key)
            results = pipe.execute()

            # If ownership set is empty, delete the key
            if len(results) >= 1 and results[-1] == 0:
                self.redis_instance.delete(ownership_key)
        except Exception as e:
            logger.debug(f"Error cleaning up message ownership for '{identifier}': {e}")

    def _cleanup_expired_operation_states(self) -> None:
        """Clean up expired operation states - Redis handles this automatically with TTL"""
        # Redis handles expiration automatically with TTL, so no action needed
        pass

    def _get_dlq_messages(self, consumer_group: str, stream: str = None) -> dict:
        """Get messages from Dead Letter Queue for inspection"""
        try:
            if stream:
                dlq_key = f"dlq:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
                messages = self.redis_instance.lrange(dlq_key, 0, -1)
                # Convert JSON dictionaries to tuples to match InlineBroker format
                dlq_tuples = []
                for msg in messages:
                    dlq_data = json.loads(
                        msg.decode() if isinstance(msg, bytes) else msg
                    )
                    # Convert to tuple format: (identifier, message, failure_reason, timestamp)
                    dlq_tuples.append(
                        (
                            dlq_data["identifier"],
                            json.loads(dlq_data["message"]),
                            dlq_data["failure_reason"],
                            float(dlq_data["timestamp"]),
                        )
                    )
                return {stream: dlq_tuples}
            else:
                # Get all DLQ keys for this consumer group
                dlq_pattern = f"dlq:*{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
                dlq_keys = self.redis_instance.keys(dlq_pattern)

                result = {}
                for dlq_key in dlq_keys:
                    if isinstance(dlq_key, bytes):
                        dlq_key = dlq_key.decode("utf-8")

                    stream_name = dlq_key.replace("dlq:", "").split(
                        CONSUMER_GROUP_SEPARATOR
                    )[0]
                    messages = self.redis_instance.lrange(dlq_key, 0, -1)
                    # Convert JSON dictionaries to tuples to match InlineBroker format
                    dlq_tuples = []
                    for msg in messages:
                        dlq_data = json.loads(
                            msg.decode() if isinstance(msg, bytes) else msg
                        )
                        # Convert to tuple format: (identifier, message, failure_reason, timestamp)
                        dlq_tuples.append(
                            (
                                dlq_data["identifier"],
                                json.loads(dlq_data["message"]),
                                dlq_data["failure_reason"],
                                float(dlq_data["timestamp"]),
                            )
                        )
                    result[stream_name] = dlq_tuples

                return result
        except Exception as e:
            logger.error(f"Error getting DLQ messages: {e}")
            return {}

    def _reprocess_dlq_message(
        self, identifier: str, consumer_group: str, stream: str
    ) -> bool:
        """Move a message from DLQ back to the main queue for reprocessing"""
        try:
            dlq_key = f"dlq:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            dlq_messages = self.redis_instance.lrange(dlq_key, 0, -1)

            for msg_bytes in dlq_messages:
                dlq_data = json.loads(
                    msg_bytes.decode() if isinstance(msg_bytes, bytes) else msg_bytes
                )
                if dlq_data["identifier"] == identifier:
                    # Use transaction to move message back and reset retry count
                    pipe = self.redis_instance.pipeline()

                    # Remove from DLQ
                    pipe.lrem(dlq_key, 1, msg_bytes)

                    # Reset retry count
                    self._set_retry_count(stream, consumer_group, identifier, 0)

                    # Add back to main queue at the beginning (using lpush for priority)
                    message = json.loads(dlq_data["message"])
                    message_tuple = (identifier, message)
                    pipe.lpush(stream, json.dumps(message_tuple))

                    # Update all consumer group positions for this stream
                    position_pattern = f"position:{stream}{CONSUMER_GROUP_SEPARATOR}*"
                    position_keys = self.redis_instance.keys(position_pattern)
                    current_position_key = (
                        f"position:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
                    )
                    for key in position_keys:
                        if isinstance(key, bytes):
                            key = key.decode("utf-8")
                        # Don't update the current consumer group's position
                        if current_position_key != key:
                            pipe.incr(key)

                    pipe.execute()
                    logger.info(f"Message '{identifier}' reprocessed from DLQ")
                    return True

            return False
        except Exception as e:
            logger.error(f"Error reprocessing DLQ message '{identifier}': {e}")
            return False

    def _get_consumer_groups_for_stream(self, stream: str) -> list[str]:
        """Get list of consumer groups for a stream - avoids keys() pattern matching"""
        try:
            # Look for all consumer groups that have positions for this stream
            # This is more efficient than using keys() pattern matching
            consumer_groups = []

            # Get all consumer group keys and check which ones have positions for this stream
            group_keys = self.redis_instance.keys("consumer_group:*")
            for key in group_keys:
                if isinstance(key, bytes):
                    key = key.decode("utf-8")

                # Extract stream and group name from the combined key
                combined_part = key.replace("consumer_group:", "")
                if CONSUMER_GROUP_SEPARATOR in combined_part:
                    key_stream, group_name = combined_part.split(
                        CONSUMER_GROUP_SEPARATOR, 1
                    )
                    # Only include groups for the specified stream
                    if key_stream == stream:
                        position_key = f"position:{stream}:{group_name}"
                        # Check if this consumer group has a position for this stream
                        if self.redis_instance.exists(position_key):
                            consumer_groups.append(group_name)

            return consumer_groups
        except Exception as e:
            logger.error(f"Error getting consumer groups for stream '{stream}': {e}")
            return []

    def _ensure_group(self, group_name: str, stream: str) -> None:
        """Bootstrap/create consumer group for Redis PubSub.

        Note: Redis PubSub doesn't have native consumer groups like Redis Streams.
        This implementation creates a Redis key to track the group existence.
        """
        group_key = f"consumer_group:{stream}{CONSUMER_GROUP_SEPARATOR}{group_name}"
        if not self.redis_instance.exists(group_key):
            self.redis_instance.hset(
                group_key,
                mapping={"created_at": str(time.time()), "consumer_count": "0"},
            )

    def _info(self) -> dict:
        """Provide information about consumer groups and consumers for Redis PubSub.

        Returns information about consumer groups stored as Redis keys.
        """
        consumer_groups = {}

        # Get all consumer group keys
        group_keys = self.redis_instance.keys("consumer_group:*")
        group_aggregates = {}  # To aggregate info by consumer group name

        for key in group_keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")

            # Extract stream and consumer group from the combined key
            combined_part = key.replace("consumer_group:", "")
            if CONSUMER_GROUP_SEPARATOR in combined_part:
                stream, group_name = combined_part.split(CONSUMER_GROUP_SEPARATOR, 1)
            else:
                # Handle legacy keys that might not have the separator
                continue

            group_info = self.redis_instance.hgetall(key)

            # Convert bytes to strings if needed
            if group_info:
                group_info = {
                    k.decode() if isinstance(k, bytes) else k: v.decode()
                    if isinstance(v, bytes)
                    else v
                    for k, v in group_info.items()
                }

                # Initialize or aggregate group data
                if group_name not in group_aggregates:
                    group_aggregates[group_name] = {
                        "consumers": [],  # Redis PubSub doesn't track individual consumers
                        "created_at": float(group_info.get("created_at", 0)),
                        "consumer_count": int(group_info.get("consumer_count", 0)),
                        "in_flight_count": 0,
                        "in_flight_messages": {},
                        "failed_count": 0,
                        "failed_messages": {},
                        "dlq_count": 0,
                        "dlq_messages": {},
                    }

                # Get counts for this specific stream+consumer_group combination
                in_flight_key = (
                    f"in_flight:{stream}{CONSUMER_GROUP_SEPARATOR}{group_name}"
                )
                failed_key = f"failed:{stream}{CONSUMER_GROUP_SEPARATOR}{group_name}"
                dlq_key = f"dlq:{stream}{CONSUMER_GROUP_SEPARATOR}{group_name}"

                # Add to aggregated counts
                in_flight_count = (
                    self.redis_instance.hlen(in_flight_key)
                    if self.redis_instance.exists(in_flight_key)
                    else 0
                )
                failed_count = (
                    self.redis_instance.llen(failed_key)
                    if self.redis_instance.exists(failed_key)
                    else 0
                )
                dlq_count = (
                    self.redis_instance.llen(dlq_key)
                    if self.redis_instance.exists(dlq_key)
                    else 0
                )

                group_aggregates[group_name]["in_flight_count"] += in_flight_count
                group_aggregates[group_name]["failed_count"] += failed_count
                group_aggregates[group_name]["dlq_count"] += dlq_count

                # Add stream-specific breakdown
                group_aggregates[group_name]["in_flight_messages"][stream] = (
                    in_flight_count
                )
                group_aggregates[group_name]["failed_messages"][stream] = failed_count
                group_aggregates[group_name]["dlq_messages"][stream] = dlq_count

        consumer_groups = group_aggregates

        return {"consumer_groups": consumer_groups}

    def _ping(self) -> bool:
        """Test basic connectivity to Redis broker"""
        try:
            return self.redis_instance.ping()
        except Exception as e:
            logger.debug(f"Redis PubSub ping failed: {e}")
            return False

    def _health_stats(self) -> dict:
        """Get Redis PubSub-specific health and performance statistics"""
        try:
            redis_info = self.redis_instance.info()

            # Calculate message counts across all streams
            message_counts = self._calculate_message_counts()

            # Calculate streams and consumer groups info
            streams_info = self._calculate_streams_info()
            consumer_groups_info = self._calculate_consumer_groups_info()

            # Extract key Redis metrics
            stats = {
                "healthy": True,
                "redis_version": redis_info.get("redis_version", "unknown"),
                "connected_clients": redis_info.get("connected_clients", 0),
                "used_memory": redis_info.get("used_memory", 0),
                "used_memory_human": redis_info.get("used_memory_human", "0B"),
                "used_memory_peak": redis_info.get("used_memory_peak", 0),
                "used_memory_peak_human": redis_info.get(
                    "used_memory_peak_human", "0B"
                ),
                "keyspace_hits": redis_info.get("keyspace_hits", 0),
                "keyspace_misses": redis_info.get("keyspace_misses", 0),
                "expired_keys": redis_info.get("expired_keys", 0),
                "evicted_keys": redis_info.get("evicted_keys", 0),
                "total_commands_processed": redis_info.get(
                    "total_commands_processed", 0
                ),
                "instantaneous_ops_per_sec": redis_info.get(
                    "instantaneous_ops_per_sec", 0
                ),
                "role": redis_info.get("role", "unknown"),
                "uptime_in_seconds": redis_info.get("uptime_in_seconds", 0),
                "tcp_port": redis_info.get("tcp_port", 0),
                "message_counts": message_counts,
                "streams": streams_info,
                "consumer_groups": consumer_groups_info,
                "memory_estimate_bytes": redis_info.get("used_memory", 0),
            }

            # Calculate hit rate if we have the data
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

            # Add configuration details (includes manual broker configuration)
            stats["configuration"] = {
                "broker_type": "redis_pubsub",
                "max_retries": self._max_retries,
                "retry_delay": self._retry_delay,
                "message_timeout": self._message_timeout,
                "enable_dlq": self._enable_dlq,
                "manual_consumer_groups": True,
                "native_ack_nack": False,  # Manual implementation
            }

            return stats

        except Exception as e:
            logger.error(f"Error getting Redis PubSub health stats: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "message_counts": {
                    "total_messages": 0,
                    "in_flight": 0,
                    "failed": 0,
                    "dlq": 0,
                },
                "streams": {"count": 0, "names": []},
                "consumer_groups": {"count": 0, "names": []},
                "memory_estimate_bytes": 0,
                "configuration": {
                    "broker_type": "redis_pubsub",
                    "error": "Failed to get configuration",
                    "max_retries": self._max_retries,
                    "retry_delay": self._retry_delay,
                    "message_timeout": self._message_timeout,
                    "enable_dlq": self._enable_dlq,
                    "manual_consumer_groups": True,
                    "native_ack_nack": False,
                },
            }

    def _ensure_connection(self) -> bool:
        """Ensure connection to Redis broker is healthy, reconnect if necessary"""
        try:
            # Test current connection
            if self.redis_instance.ping():
                return True

            # Connection failed, try to reconnect
            logger.info("Redis PubSub connection failed, attempting to reconnect...")

            # Create a new Redis instance with the same connection info
            self.redis_instance = redis.Redis.from_url(self.conn_info["URI"])

            # Test the new connection
            if self.redis_instance.ping():
                logger.info("Redis PubSub connection restored")
                return True
            else:
                logger.error("Failed to restore Redis PubSub connection")
                return False

        except Exception as e:
            logger.error(f"Error ensuring Redis PubSub connection: {e}")
            try:
                # Last attempt - create completely new connection
                self.redis_instance = redis.Redis.from_url(self.conn_info["URI"])
                if self.redis_instance.ping():
                    logger.info("Redis PubSub connection restored after recreation")
                    return True
            except Exception as reconnect_error:
                logger.error(f"Failed to reconnect to Redis PubSub: {reconnect_error}")

            return False

    def _calculate_message_counts(self) -> dict:
        """Calculate message counts across all streams"""
        try:
            streams_to_check = self._get_streams_to_check()
            total_messages = 0
            total_in_flight = 0
            total_failed = 0
            total_dlq = 0

            for stream in streams_to_check:
                try:
                    # Get stream length (total messages)
                    stream_length = self.redis_instance.llen(stream)
                    total_messages += stream_length

                    # Get in-flight, failed, and DLQ counts for all consumer groups in this stream
                    consumer_groups = self._get_consumer_groups_for_stream(stream)
                    for consumer_group in consumer_groups:
                        # Count in-flight messages
                        in_flight_key = f"in_flight:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
                        if self.redis_instance.exists(in_flight_key):
                            total_in_flight += self.redis_instance.hlen(in_flight_key)

                        # Count failed messages
                        failed_key = (
                            f"failed:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
                        )
                        if self.redis_instance.exists(failed_key):
                            total_failed += self.redis_instance.llen(failed_key)

                        # Count DLQ messages
                        dlq_key = (
                            f"dlq:{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
                        )
                        if self.redis_instance.exists(dlq_key):
                            total_dlq += self.redis_instance.llen(dlq_key)

                except redis.ResponseError:
                    # Stream might not exist
                    pass

            return {
                "total_messages": total_messages,
                "in_flight": total_in_flight,
                "failed": total_failed,
                "dlq": total_dlq,
            }

        except Exception as e:
            logger.debug(f"Error calculating message counts: {e}")
            return {"total_messages": 0, "in_flight": 0, "failed": 0, "dlq": 0}

    def _get_streams_to_check(self) -> set:
        """Get set of streams to check for info"""
        streams = set(self._subscribers.keys())

        # Also get streams from consumer group keys and position keys
        try:
            # Get streams from consumer group keys
            group_keys = self.redis_instance.keys("consumer_group:*")
            for key in group_keys:
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                combined_part = key.replace("consumer_group:", "")
                if CONSUMER_GROUP_SEPARATOR in combined_part:
                    stream_name = combined_part.split(CONSUMER_GROUP_SEPARATOR, 1)[0]
                    streams.add(stream_name)

            # Get streams from position keys
            position_keys = self.redis_instance.keys("position:*")
            for key in position_keys:
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                combined_part = key.replace("position:", "")
                if CONSUMER_GROUP_SEPARATOR in combined_part:
                    stream_name = combined_part.split(CONSUMER_GROUP_SEPARATOR, 1)[0]
                    streams.add(stream_name)

        except Exception as e:
            logger.debug(f"Error getting streams to check: {e}")

        return streams

    def _calculate_streams_info(self) -> dict:
        """Calculate streams information"""
        try:
            streams_to_check = self._get_streams_to_check()
            # Filter out streams that don't actually exist as Redis lists
            existing_streams = []
            for stream in streams_to_check:
                try:
                    if self.redis_instance.exists(stream):
                        existing_streams.append(stream)
                except redis.ResponseError:
                    # Stream doesn't exist, skip it
                    pass

            return {"count": len(existing_streams), "names": sorted(existing_streams)}
        except Exception as e:
            logger.debug(f"Error calculating streams info: {e}")
            return {"count": 0, "names": []}

    def _calculate_consumer_groups_info(self) -> dict:
        """Calculate consumer groups information"""
        try:
            # Get all unique consumer group names across all streams
            consumer_groups = set()
            group_keys = self.redis_instance.keys("consumer_group:*")
            for key in group_keys:
                if isinstance(key, bytes):
                    key = key.decode("utf-8")
                combined_part = key.replace("consumer_group:", "")
                if CONSUMER_GROUP_SEPARATOR in combined_part:
                    _, group_name = combined_part.split(CONSUMER_GROUP_SEPARATOR, 1)
                    consumer_groups.add(group_name)

            return {"count": len(consumer_groups), "names": sorted(consumer_groups)}
        except Exception as e:
            logger.debug(f"Error calculating consumer groups info: {e}")
            return {"count": 0, "names": []}

    def _data_reset(self) -> None:
        self.redis_instance.flushall()
