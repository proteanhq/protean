import logging
import time
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Dict

from protean.port.broker import BaseBroker, BrokerCapabilities, OperationState

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Constants
CONSUMER_GROUP_SEPARATOR = ":"
MAX_RETRIES = 3
RETRY_DELAY = 1.0
BACKOFF_MULTIPLIER = 2.0
MESSAGE_TIMEOUT = 300.0
ENABLE_DLQ = True
OPERATION_STATE_TTL_MAX = 60.0


class InlineBroker(BaseBroker):
    __broker__ = "inline"

    def __init__(
        self, name: str, domain: "Domain", conn_info: Dict[str, str | bool]
    ) -> None:
        super().__init__(name, domain, conn_info)

        # In case of `InlineBroker`, the `IS_ASYNC` value will always be `False`.
        conn_info["IS_ASYNC"] = False

        # Configuration for retry behavior and timeouts
        self._max_retries = conn_info.get("max_retries", MAX_RETRIES)
        self._retry_delay = conn_info.get("retry_delay", RETRY_DELAY)
        self._backoff_multiplier = conn_info.get(
            "backoff_multiplier", BACKOFF_MULTIPLIER
        )
        self._message_timeout = conn_info.get(
            "message_timeout", MESSAGE_TIMEOUT
        )  # 5 minutes default
        self._enable_dlq = conn_info.get("enable_dlq", ENABLE_DLQ)
        self._operation_state_ttl = max(
            int(self._message_timeout * 3), OPERATION_STATE_TTL_MAX
        )  # At least 1 minute

        # Initialize storage for messages
        self._messages = defaultdict(list)

        # Initialize storage for consumer groups
        # Structure: {stream:group_name: {consumers: set(), created_at: timestamp}}
        self._consumer_groups = {}

        # Initialize storage for in-flight messages per consumer group
        # Structure: {stream:consumer_group: {identifier: (identifier, message, timestamp)}}
        self._in_flight = defaultdict(dict)

        # Initialize storage for failed messages (nacked messages waiting for retry)
        # Structure: {stream:consumer_group: [(identifier, message, retry_count, next_retry_time)]}
        self._failed_messages = defaultdict(list)

        # Track retry counts per message per consumer group
        # Structure: {stream:consumer_group: {identifier: retry_count}}
        self._retry_counts = defaultdict(dict)

        # Track read positions per consumer group to support multiple consumer groups
        # Structure: {stream:consumer_group: position}
        self._consumer_positions = defaultdict(int)

        # Track message ownership per consumer group
        # Structure: {identifier: {consumer_group: bool}}
        self._message_ownership = defaultdict(dict)

        # Dead Letter Queue for permanently failed messages
        # Structure: {stream:consumer_group: [(identifier, message, failure_reason, timestamp)]}
        self._dead_letter_queue = defaultdict(list)

        # Track operation states for idempotency
        # Structure: {consumer_group: {identifier: (state, timestamp)}}
        self._operation_states = defaultdict(dict)

    @property
    def capabilities(self) -> BrokerCapabilities:
        """InlineBroker provides full manual broker capabilities for testing."""
        return BrokerCapabilities.RELIABLE_MESSAGING

    def _publish(self, stream: str, message: dict) -> str:
        """Publish a message dict to the stream"""
        # We always generate a new identifier for inline broker, since
        #   there is underlying persistence layer to generate identifiers.
        identifier = str(uuid.uuid4())

        # Store message as tuple (identifier, message)
        self._messages[stream].append((identifier, message))

        return identifier

    def _read(
        self, stream: str, consumer_group: str, no_of_messages: int
    ) -> list[tuple[str, dict]]:
        """Default implementation using _get_next"""
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

    def _get_next(self, stream: str, consumer_group: str) -> tuple[str, dict] | None:
        """Get next message in stream for a specific consumer group"""
        # Ensure consumer group exists (create if it doesn't)
        self._ensure_group(consumer_group, stream)

        # Create combined group key for this stream+consumer_group
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"

        # Clean up stale in-flight messages first
        self._cleanup_stale_messages(consumer_group, self._message_timeout)

        # First, check for any failed messages that are ready for retry
        self._requeue_failed_messages(stream, consumer_group)

        # Check current position for this consumer group
        position = self._consumer_positions[group_key]

        # Check if there's a message at this position
        if position < len(self._messages[stream]):
            identifier, message = self._messages[stream][position]

            # Increment position for this consumer group
            self._consumer_positions[group_key] += 1

            # Track message ownership
            self._message_ownership[identifier][consumer_group] = True

            # Clear any previous operation state for fresh processing
            self._clear_operation_state(consumer_group, identifier)

            # Move message to in-flight status
            self._store_in_flight_message(stream, consumer_group, identifier, message)

            return (identifier, message)

        # There is no message in the stream for this consumer group
        return None

    def _ack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Template method for message acknowledgment with common logic"""
        try:
            # Clean up expired operation states first
            self._cleanup_expired_operation_states()

            # Check for idempotency
            current_state = self._get_operation_state(consumer_group, identifier)
            if current_state == OperationState.ACKNOWLEDGED:
                logger.debug(
                    f"Message '{identifier}' already acknowledged by consumer group '{consumer_group}' (idempotent)"
                )
                return False
            elif current_state == OperationState.NACKED:
                logger.warning(
                    f"Cannot ack message '{identifier}' - already nacked by consumer group '{consumer_group}'"
                )
                return False

            # Validate consumer group exists
            if not self._validate_consumer_group(consumer_group):
                logger.warning(f"Consumer group '{consumer_group}' does not exist")
                return False

            # Validate message ownership
            if not self._validate_message_ownership(identifier, consumer_group):
                logger.warning(
                    f"Message '{identifier}' was not delivered to consumer group '{consumer_group}'"
                )
                return False

            # Check if message is still in-flight
            if not self._is_in_flight_message(stream, consumer_group, identifier):
                logger.warning(
                    f"Message '{identifier}' not found in in-flight status for consumer group '{consumer_group}'"
                )
                return False

            # Set operation state to acknowledged
            self._store_operation_state(
                consumer_group, identifier, OperationState.ACKNOWLEDGED
            )

            # Remove message from in-flight status
            self._remove_in_flight_message(stream, consumer_group, identifier)

            # Clean up retry count tracking
            self._remove_retry_count(stream, consumer_group, identifier)

            # Remove any failed message entry
            self._remove_failed_message(stream, consumer_group, identifier)

            # Clean up message ownership tracking (broker-specific implementation)
            self._cleanup_message_ownership(identifier, consumer_group)

            # Log successful acknowledgment (non-critical operation)
            try:
                logger.debug(
                    f"Message '{identifier}' acknowledged by consumer group '{consumer_group}'"
                )
            except Exception as log_error:
                # Logging failure shouldn't cause ACK to fail
                logger.error(
                    f"Failed to log ACK success for message '{identifier}': {log_error}"
                )
                # Clean up operation state since we can't reliably track the operation
                self._clear_operation_state(consumer_group, identifier)
                return False

            return True

        except Exception as e:
            logger.error(f"Error acknowledging message '{identifier}': {e}")
            # Clean up operation state on failure
            self._clear_operation_state(consumer_group, identifier)
            return False

    def _nack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Template method for negative acknowledgment with common logic"""
        try:
            # Clean up expired operation states first
            self._cleanup_expired_operation_states()

            # Check for idempotency
            current_state = self._get_operation_state(consumer_group, identifier)
            if current_state == OperationState.NACKED:
                logger.debug(
                    f"Message '{identifier}' already nacked by consumer group '{consumer_group}' (idempotent)"
                )
                return False
            elif current_state == OperationState.ACKNOWLEDGED:
                logger.warning(
                    f"Cannot nack message '{identifier}' - already acknowledged by consumer group '{consumer_group}'"
                )
                return False

            # Validate consumer group exists
            if not self._validate_consumer_group(consumer_group):
                logger.warning(f"Consumer group '{consumer_group}' does not exist")
                return False

            # Validate message ownership
            if not self._validate_message_ownership(identifier, consumer_group):
                logger.warning(
                    f"Message '{identifier}' was not delivered to consumer group '{consumer_group}'"
                )
                return False

            # Get message from in-flight status
            message_data = self._get_in_flight_message(
                stream, consumer_group, identifier
            )
            if not message_data:
                logger.warning(
                    f"Message '{identifier}' not found in in-flight status for consumer group '{consumer_group}'"
                )
                return False

            _, message = message_data

            # Get current retry count and increment it
            retry_count = self._get_retry_count(stream, consumer_group, identifier)
            new_retry_count = retry_count + 1

            if new_retry_count <= self._max_retries:
                return self._handle_nack_with_retry(
                    stream,
                    identifier,
                    consumer_group,
                    message,
                    retry_count,
                    new_retry_count,
                )
            else:
                return self._handle_nack_max_retries_exceeded(
                    stream, identifier, consumer_group, message, new_retry_count
                )

        except Exception as e:
            logger.error(f"Error nacking message '{identifier}': {e}")
            # Clean up operation state on failure
            self._clear_operation_state(consumer_group, identifier)
            return False

    def _handle_nack_with_retry(
        self,
        stream: str,
        identifier: str,
        consumer_group: str,
        message: dict,
        retry_count: int,
        new_retry_count: int,
    ) -> bool:
        """Handle nack with retry"""
        try:
            # Set operation state to nacked
            self._store_operation_state(
                consumer_group, identifier, OperationState.NACKED
            )

            # Remove from in-flight
            self._remove_in_flight_message(stream, consumer_group, identifier)

            # Update retry count
            self._set_retry_count(stream, consumer_group, identifier, new_retry_count)

            # Calculate next retry time with exponential backoff
            delay = self._retry_delay * (self._backoff_multiplier**retry_count)
            next_retry_time = time.time() + delay

            # Remove any existing failed message entry
            self._remove_failed_message(stream, consumer_group, identifier)

            # Store in failed messages for retry
            self._store_failed_message(
                stream,
                consumer_group,
                identifier,
                message,
                new_retry_count,
                next_retry_time,
            )

            # Log successful nack (non-critical operation)
            try:
                logger.debug(
                    f"Message '{identifier}' nacked, retry {new_retry_count}/{self._max_retries} in {delay:.2f}s"
                )
            except Exception as log_error:
                # Logging failure shouldn't cause NACK to fail
                logger.error(
                    f"Failed to log NACK success for message '{identifier}': {log_error}"
                )

            return True

        except Exception as e:
            logger.error(
                f"Error handling nack with retry for message '{identifier}': {e}"
            )
            self._clear_operation_state(consumer_group, identifier)
            return False

    def _handle_nack_max_retries_exceeded(
        self,
        stream: str,
        identifier: str,
        consumer_group: str,
        message: dict,
        new_retry_count: int,
    ) -> bool:
        """Handle nack when max retries exceeded"""
        try:
            # Set operation state to failed
            self._store_operation_state(
                consumer_group, identifier, OperationState.FAILED
            )

            # Remove from in-flight
            self._remove_in_flight_message(stream, consumer_group, identifier)

            # Max retries exceeded - move to DLQ or discard
            if self._enable_dlq:
                self._store_dlq_message(
                    stream, consumer_group, identifier, message, "max_retries_exceeded"
                )
                logger.warning(
                    f"Message '{identifier}' moved to DLQ after {self._max_retries} retries"
                )
            else:
                logger.warning(
                    f"Message '{identifier}' discarded after {self._max_retries} retries"
                )

            # Clean up tracking
            self._remove_retry_count(stream, consumer_group, identifier)
            self._remove_failed_message(stream, consumer_group, identifier)
            self._cleanup_message_ownership(identifier, consumer_group)

            return True

        except Exception as e:
            logger.error(
                f"Error handling max retries exceeded for message '{identifier}': {e}"
            )
            self._clear_operation_state(consumer_group, identifier)
            return False

    def _requeue_failed_messages(self, stream: str, consumer_group: str) -> None:
        """Move failed messages back to the main queue if they're ready for retry"""
        try:
            ready_messages = self._get_retry_ready_messages(stream, consumer_group)
            if ready_messages:
                self._requeue_messages(stream, consumer_group, ready_messages)
        except Exception as e:
            logger.error(
                f"Error requeuing failed messages for {consumer_group}:{stream}: {e}"
            )

    def get_dlq_messages(self, consumer_group: str, stream: str = None) -> dict:
        """Get messages from Dead Letter Queue for inspection"""
        return self._get_dlq_messages(consumer_group, stream)

    def reprocess_dlq_message(
        self, identifier: str, consumer_group: str, stream: str
    ) -> bool:
        """Move a message from DLQ back to the main queue for reprocessing"""
        return self._reprocess_dlq_message(identifier, consumer_group, stream)

    # Manual broker implementation methods
    def _store_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str, message: dict
    ) -> None:
        """Store a message in in-flight status"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self._in_flight[group_key][identifier] = (
            identifier,
            message,
            time.time(),
        )

    def _remove_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove a message from in-flight status"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        if identifier in self._in_flight[group_key]:
            del self._in_flight[group_key][identifier]

    def _is_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> bool:
        """Check if a message is in in-flight status"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        return identifier in self._in_flight[group_key]

    def _get_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> tuple[str, dict] | None:
        """Get in-flight message data"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        if identifier in self._in_flight[group_key]:
            identifier, message, _ = self._in_flight[group_key][identifier]
            return (identifier, message)
        return None

    def _store_operation_state(
        self, consumer_group: str, identifier: str, state: OperationState
    ) -> None:
        """Store operation state for idempotency"""
        self._operation_states[consumer_group][identifier] = (state, time.time())

    def _get_operation_state(
        self, consumer_group: str, identifier: str
    ) -> OperationState | None:
        """Get current operation state"""
        if identifier in self._operation_states[consumer_group]:
            state, timestamp = self._operation_states[consumer_group][identifier]
            # Check if not expired
            if time.time() - timestamp < self._operation_state_ttl:
                return state
            else:
                # Clean up expired state
                del self._operation_states[consumer_group][identifier]
        return None

    def _clear_operation_state(self, consumer_group: str, identifier: str) -> None:
        """Clear operation state"""
        if identifier in self._operation_states[consumer_group]:
            del self._operation_states[consumer_group][identifier]

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
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self._failed_messages[group_key].append(
            (identifier, message, retry_count, next_retry_time)
        )

    def _remove_failed_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove a failed message from retry queue"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        failed_messages = self._failed_messages[group_key]
        self._failed_messages[group_key] = [
            (msg_id, msg, retry_count, next_retry_time)
            for msg_id, msg, retry_count, next_retry_time in failed_messages
            if msg_id != identifier
        ]

    def _get_retry_ready_messages(
        self, stream: str, consumer_group: str
    ) -> list[tuple[str, dict]]:
        """Get messages ready for retry and remove them from failed queue"""
        current_time = time.time()
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        failed_messages = self._failed_messages[group_key]

        # Find messages ready for retry
        ready_for_retry = []
        remaining_failed = []

        for identifier, message, retry_count, next_retry_time in failed_messages:
            if next_retry_time <= current_time:
                ready_for_retry.append((identifier, message))
            else:
                remaining_failed.append(
                    (identifier, message, retry_count, next_retry_time)
                )

        # Update failed messages list
        self._failed_messages[group_key] = remaining_failed

        return ready_for_retry

    def _store_dlq_message(
        self,
        stream: str,
        consumer_group: str,
        identifier: str,
        message: dict,
        failure_reason: str,
    ) -> None:
        """Store a message in Dead Letter Queue"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self._dead_letter_queue[group_key].append(
            (identifier, message, failure_reason, time.time())
        )

    def _validate_consumer_group(self, consumer_group: str) -> bool:
        """Validate that the consumer group exists"""
        # For inline broker, we need to check all streams for this consumer group
        for group_key in self._consumer_groups:
            if group_key.endswith(f"{CONSUMER_GROUP_SEPARATOR}{consumer_group}"):
                return True
        return False

    def _validate_message_ownership(self, identifier: str, consumer_group: str) -> bool:
        """Validate that the message was delivered to the specified consumer group"""
        return (
            identifier in self._message_ownership
            and consumer_group in self._message_ownership[identifier]
        )

    def _cleanup_stale_messages(
        self, consumer_group: str, timeout_seconds: float
    ) -> None:
        """Remove messages that have been in-flight too long"""
        current_time = time.time()
        cutoff_time = current_time - timeout_seconds

        # Find all group keys for this consumer group
        matching_group_keys = [
            group_key
            for group_key in self._in_flight.keys()
            if group_key.endswith(f"{CONSUMER_GROUP_SEPARATOR}{consumer_group}")
        ]

        for group_key in matching_group_keys:
            # Extract stream name from group key
            stream = group_key.split(CONSUMER_GROUP_SEPARATOR)[0]

            stale_messages = []
            for identifier, (msg_id, message, timestamp) in list(
                self._in_flight[group_key].items()
            ):
                if timestamp < cutoff_time:
                    stale_messages.append((identifier, message))
                    # Remove from in-flight
                    del self._in_flight[group_key][identifier]

                    # Move to DLQ if enabled
                    if self._enable_dlq:
                        self._store_dlq_message(
                            stream, consumer_group, identifier, message, "timeout"
                        )
                        logger.warning(
                            f"Message '{identifier}' moved to DLQ due to timeout"
                        )

                    # Clean up tracking
                    self._remove_retry_count(stream, consumer_group, identifier)
                    self._cleanup_message_ownership(identifier, consumer_group)

    def _get_retry_count(
        self, stream: str, consumer_group: str, identifier: str
    ) -> int:
        """Get current retry count for a message"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        return self._retry_counts[group_key].get(identifier, 0)

    def _set_retry_count(
        self, stream: str, consumer_group: str, identifier: str, count: int
    ) -> None:
        """Set retry count for a message"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self._retry_counts[group_key][identifier] = count

    def _remove_retry_count(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove retry count tracking for a message"""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        if identifier in self._retry_counts[group_key]:
            del self._retry_counts[group_key][identifier]

    def _requeue_messages(
        self, stream: str, consumer_group: str, messages: list[tuple[str, dict]]
    ) -> None:
        """Requeue messages back to the main queue"""
        if messages:
            # Add ready messages back to the queue at the current position for this consumer group
            group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            current_position = self._consumer_positions[group_key]

            # Insert messages in reverse order to maintain order
            for identifier, message in reversed(messages):
                self._messages[stream].insert(current_position, (identifier, message))
                # Adjust all consumer group positions that are at or beyond this position
                for other_group_key in self._consumer_positions:
                    if (
                        other_group_key != group_key
                        and other_group_key.startswith(
                            f"{stream}{CONSUMER_GROUP_SEPARATOR}"
                        )
                        and self._consumer_positions[other_group_key]
                        >= current_position
                    ):
                        self._consumer_positions[other_group_key] += 1

    def _cleanup_message_ownership(self, identifier: str, consumer_group: str) -> None:
        """Clean up message ownership tracking"""
        if identifier in self._message_ownership:
            if consumer_group in self._message_ownership[identifier]:
                del self._message_ownership[identifier][consumer_group]
            if not self._message_ownership[identifier]:
                del self._message_ownership[identifier]

    def _cleanup_expired_operation_states(self) -> None:
        """Clean up expired operation states"""
        current_time = time.time()
        cutoff_time = current_time - self._operation_state_ttl

        for consumer_group in list(self._operation_states.keys()):
            for identifier in list(self._operation_states[consumer_group].keys()):
                state, timestamp = self._operation_states[consumer_group][identifier]
                if timestamp < cutoff_time:
                    del self._operation_states[consumer_group][identifier]

            # Clean up empty consumer group entries
            if not self._operation_states[consumer_group]:
                del self._operation_states[consumer_group]

    def _get_dlq_messages(self, consumer_group: str, stream: str = None) -> dict:
        """Get messages from Dead Letter Queue for inspection"""
        if stream:
            group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            return {stream: list(self._dead_letter_queue[group_key])}
        else:
            # Get all DLQ messages for this consumer group across all streams
            result = {}
            for group_key in self._dead_letter_queue:
                if group_key.endswith(f"{CONSUMER_GROUP_SEPARATOR}{consumer_group}"):
                    stream_name = group_key.split(CONSUMER_GROUP_SEPARATOR)[0]
                    result[stream_name] = list(self._dead_letter_queue[group_key])
            return result

    def _reprocess_dlq_message(
        self, identifier: str, consumer_group: str, stream: str
    ) -> bool:
        """Move a message from DLQ back to the main queue for reprocessing"""
        try:
            group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            dlq_messages = self._dead_letter_queue[group_key]
            for i, (msg_id, message, failure_reason, timestamp) in enumerate(
                dlq_messages
            ):
                if msg_id == identifier:
                    # Remove from DLQ
                    del dlq_messages[i]

                    # Reset retry count
                    self._set_retry_count(stream, consumer_group, identifier, 0)

                    # Add back to main queue at current position
                    current_position = self._consumer_positions[group_key]
                    self._messages[stream].insert(
                        current_position, (identifier, message)
                    )

                    # Adjust all consumer group positions for this stream
                    for other_group_key in self._consumer_positions:
                        if (
                            other_group_key != group_key
                            and other_group_key.startswith(
                                f"{stream}{CONSUMER_GROUP_SEPARATOR}"
                            )
                            and self._consumer_positions[other_group_key]
                            >= current_position
                        ):
                            self._consumer_positions[other_group_key] += 1

                    logger.info(f"Message '{identifier}' reprocessed from DLQ")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error reprocessing DLQ message '{identifier}': {e}")
            return False

    def _ensure_group(self, group_name: str, stream: str) -> None:
        """Bootstrap/create consumer group."""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{group_name}"
        if group_key not in self._consumer_groups:
            self._consumer_groups[group_key] = {
                "consumers": set(),
                "created_at": time.time(),
            }

    def _info(self) -> dict:
        """Provide information about consumer groups and consumers."""
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
                    "in_flight_messages": {},
                    "failed_messages": {},
                    "dlq_messages": {},
                }

            # Add stream-specific information
            consumer_groups_info[consumer_group]["in_flight_messages"][stream] = len(
                self._in_flight[group_key]
            )
            consumer_groups_info[consumer_group]["failed_messages"][stream] = len(
                self._failed_messages[group_key]
            )
            consumer_groups_info[consumer_group]["dlq_messages"][stream] = len(
                self._dead_letter_queue[group_key]
            )

        return {"consumer_groups": consumer_groups_info}

    def _data_reset(self) -> None:
        """Flush all data in broker instance"""
        self._messages.clear()
        self._consumer_groups.clear()
        self._in_flight.clear()
        self._failed_messages.clear()
        self._retry_counts.clear()
        self._consumer_positions.clear()
        self._message_ownership.clear()
        self._dead_letter_queue.clear()
        self._operation_states.clear()

    def _ping(self) -> bool:
        """Test connectivity to the inline broker.

        Since InlineBroker is in-memory, it's always available.

        Returns:
            bool: Always True for inline broker
        """
        return True

    def _health_stats(self) -> dict:
        """Get health statistics for the inline broker.

        Returns:
            dict: Health statistics including message counts and consumer group info
        """
        # Calculate total messages across all streams
        total_messages = sum(len(messages) for messages in self._messages.values())

        # Calculate total in-flight messages across all consumer groups
        total_in_flight = sum(len(in_flight) for in_flight in self._in_flight.values())

        # Calculate total failed messages across all consumer groups
        total_failed = sum(len(failed) for failed in self._failed_messages.values())

        # Calculate total DLQ messages across all consumer groups
        total_dlq = sum(len(dlq) for dlq in self._dead_letter_queue.values())

        # Get unique streams and consumer groups
        streams = set(self._messages.keys())
        consumer_groups = set()
        for group_key in self._consumer_groups.keys():
            if CONSUMER_GROUP_SEPARATOR in group_key:
                _, group_name = group_key.split(CONSUMER_GROUP_SEPARATOR, 1)
                consumer_groups.add(group_name)

        # Calculate memory usage estimate (rough approximation)
        memory_estimate = (
            total_messages * 100  # Rough estimate per message
            + total_in_flight * 150  # In-flight messages have more metadata
            + total_failed * 150  # Failed messages have retry info
            + total_dlq * 150  # DLQ messages have failure info
        )

        return {
            "healthy": True,  # InlineBroker is always healthy
            "message_counts": {
                "total_messages": total_messages,
                "in_flight": total_in_flight,
                "failed": total_failed,
                "dlq": total_dlq,
            },
            "streams": {"count": len(streams), "names": list(streams)},
            "consumer_groups": {
                "count": len(consumer_groups),
                "names": list(consumer_groups),
            },
            "memory_estimate_bytes": memory_estimate,
            "configuration": {
                "max_retries": self._max_retries,
                "retry_delay": self._retry_delay,
                "message_timeout": self._message_timeout,
                "enable_dlq": self._enable_dlq,
            },
        }

    def _ensure_connection(self) -> bool:
        """Ensure connection to the inline broker.

        Since InlineBroker is in-memory, no external connection is needed.

        Returns:
            bool: Always True for inline broker
        """
        return True
