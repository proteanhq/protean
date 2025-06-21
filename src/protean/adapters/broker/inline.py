import logging
import time
import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Dict

from protean.port.broker import BaseManualBroker, OperationState

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class InlineBroker(BaseManualBroker):
    __broker__ = "inline"

    def __init__(
        self, name: str, domain: "Domain", conn_info: Dict[str, str | bool]
    ) -> None:
        super().__init__(name, domain, conn_info)

        # In case of `InlineBroker`, the `IS_ASYNC` value will always be `False`.
        conn_info["IS_ASYNC"] = False

        # Initialize storage for messages
        self._messages = defaultdict(list)

        # Initialize storage for consumer groups
        # Structure: {group_name: {consumers: set(), created_at: timestamp}}
        self._consumer_groups = {}

        # Initialize storage for in-flight messages per consumer group
        # Structure: {consumer_group: {stream: {identifier: (identifier, message, timestamp)}}}
        self._in_flight = defaultdict(lambda: defaultdict(dict))

        # Initialize storage for failed messages (nacked messages waiting for retry)
        # Structure: {consumer_group: {stream: [(identifier, message, retry_count, next_retry_time)]}}
        self._failed_messages = defaultdict(lambda: defaultdict(list))

        # Track retry counts per message per consumer group
        # Structure: {consumer_group: {stream: {identifier: retry_count}}}
        self._retry_counts = defaultdict(lambda: defaultdict(dict))

        # Track read positions per consumer group to support multiple consumer groups
        # Structure: {consumer_group: {stream: position}}
        self._consumer_positions = defaultdict(lambda: defaultdict(int))

        # Track message ownership per consumer group
        # Structure: {identifier: {consumer_group: bool}}
        self._message_ownership = defaultdict(dict)

        # Dead Letter Queue for permanently failed messages
        # Structure: {consumer_group: {stream: [(identifier, message, failure_reason, timestamp)]}}
        self._dead_letter_queue = defaultdict(lambda: defaultdict(list))

        # Track operation states for idempotency
        # Structure: {consumer_group: {identifier: (state, timestamp)}}
        self._operation_states = defaultdict(dict)

    def _publish(self, stream: str, message: dict) -> str:
        """Publish a message dict to the stream"""
        # We always generate a new identifier for inline broker, since
        #   there is underlying persistence layer to generate identifiers.
        identifier = str(uuid.uuid4())

        # Store message as tuple (identifier, message)
        self._messages[stream].append((identifier, message))

        return identifier

    def _get_next(self, stream: str, consumer_group: str) -> tuple[str, dict] | None:
        """Get next message in stream for a specific consumer group"""
        # Ensure consumer group exists (create if it doesn't)
        self._ensure_group(consumer_group)

        # Clean up stale in-flight messages first
        self._cleanup_stale_messages(consumer_group, self._message_timeout)

        # First, check for any failed messages that are ready for retry
        self._requeue_failed_messages(stream, consumer_group)

        # Check current position for this consumer group
        position = self._consumer_positions[consumer_group][stream]

        # Check if there's a message at this position
        if position < len(self._messages[stream]):
            identifier, message = self._messages[stream][position]

            # Increment position for this consumer group
            self._consumer_positions[consumer_group][stream] += 1

            # Track message ownership
            self._message_ownership[identifier][consumer_group] = True

            # Clear any previous operation state for fresh processing
            self._clear_operation_state(consumer_group, identifier)

            # Move message to in-flight status
            self._store_in_flight_message(stream, consumer_group, identifier, message)

            return (identifier, message)

        # There is no message in the stream for this consumer group
        return None

    # BaseManualBroker abstract method implementations
    def _store_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str, message: dict
    ) -> None:
        """Store a message in in-flight status"""
        self._in_flight[consumer_group][stream][identifier] = (
            identifier,
            message,
            time.time(),
        )

    def _remove_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove a message from in-flight status"""
        if identifier in self._in_flight[consumer_group][stream]:
            del self._in_flight[consumer_group][stream][identifier]

    def _is_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> bool:
        """Check if a message is in in-flight status"""
        return identifier in self._in_flight[consumer_group][stream]

    def _get_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> tuple[str, dict] | None:
        """Get in-flight message data"""
        if identifier in self._in_flight[consumer_group][stream]:
            identifier, message, _ = self._in_flight[consumer_group][stream][identifier]
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
        self._failed_messages[consumer_group][stream].append(
            (identifier, message, retry_count, next_retry_time)
        )

    def _remove_failed_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove a failed message from retry queue"""
        failed_messages = self._failed_messages[consumer_group][stream]
        self._failed_messages[consumer_group][stream] = [
            (msg_id, msg, retry_count, next_retry_time)
            for msg_id, msg, retry_count, next_retry_time in failed_messages
            if msg_id != identifier
        ]

    def _get_retry_ready_messages(
        self, stream: str, consumer_group: str
    ) -> list[tuple[str, dict]]:
        """Get messages ready for retry and remove them from failed queue"""
        current_time = time.time()
        failed_messages = self._failed_messages[consumer_group][stream]

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
        self._failed_messages[consumer_group][stream] = remaining_failed

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
        self._dead_letter_queue[consumer_group][stream].append(
            (identifier, message, failure_reason, time.time())
        )

    def _validate_consumer_group(self, consumer_group: str) -> bool:
        """Validate that the consumer group exists"""
        return consumer_group in self._consumer_groups

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

        for stream in list(self._in_flight[consumer_group].keys()):
            stale_messages = []
            for identifier, (msg_id, message, timestamp) in list(
                self._in_flight[consumer_group][stream].items()
            ):
                if timestamp < cutoff_time:
                    stale_messages.append((identifier, message))
                    # Remove from in-flight
                    del self._in_flight[consumer_group][stream][identifier]

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
        return self._retry_counts[consumer_group][stream].get(identifier, 0)

    def _set_retry_count(
        self, stream: str, consumer_group: str, identifier: str, count: int
    ) -> None:
        """Set retry count for a message"""
        self._retry_counts[consumer_group][stream][identifier] = count

    def _remove_retry_count(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove retry count tracking for a message"""
        if identifier in self._retry_counts[consumer_group][stream]:
            del self._retry_counts[consumer_group][stream][identifier]

    def _requeue_messages(
        self, stream: str, consumer_group: str, messages: list[tuple[str, dict]]
    ) -> None:
        """Requeue messages back to the main queue"""
        if messages:
            # Add ready messages back to the queue at the current position for this consumer group
            current_position = self._consumer_positions[consumer_group][stream]

            # Insert messages in reverse order to maintain order
            for identifier, message in reversed(messages):
                self._messages[stream].insert(current_position, (identifier, message))
                # Adjust all consumer group positions that are at or beyond this position
                for cgroup in self._consumer_positions:
                    if (
                        cgroup != consumer_group
                        and self._consumer_positions[cgroup][stream] >= current_position
                    ):
                        self._consumer_positions[cgroup][stream] += 1

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
            return {stream: list(self._dead_letter_queue[consumer_group][stream])}
        else:
            return dict(self._dead_letter_queue[consumer_group])

    def _reprocess_dlq_message(
        self, identifier: str, consumer_group: str, stream: str
    ) -> bool:
        """Move a message from DLQ back to the main queue for reprocessing"""
        try:
            dlq_messages = self._dead_letter_queue[consumer_group][stream]
            for i, (msg_id, message, failure_reason, timestamp) in enumerate(
                dlq_messages
            ):
                if msg_id == identifier:
                    # Remove from DLQ
                    del dlq_messages[i]

                    # Reset retry count
                    self._set_retry_count(stream, consumer_group, identifier, 0)

                    # Add back to main queue at current position
                    current_position = self._consumer_positions[consumer_group][stream]
                    self._messages[stream].insert(
                        current_position, (identifier, message)
                    )

                    # Adjust all consumer group positions
                    for cgroup in self._consumer_positions:
                        if (
                            cgroup != consumer_group
                            and self._consumer_positions[cgroup][stream]
                            >= current_position
                        ):
                            self._consumer_positions[cgroup][stream] += 1

                    logger.info(f"Message '{identifier}' reprocessed from DLQ")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error reprocessing DLQ message '{identifier}': {e}")
            return False

    def _ensure_group(self, group_name: str) -> None:
        """Bootstrap/create consumer group."""
        if group_name not in self._consumer_groups:
            self._consumer_groups[group_name] = {
                "consumers": set(),
                "created_at": time.time(),
            }

    def _info(self) -> dict:
        """Provide information about consumer groups and consumers."""
        return {
            "consumer_groups": {
                group_name: {
                    "consumers": list(group_info["consumers"]),
                    "created_at": group_info["created_at"],
                    "consumer_count": len(group_info["consumers"]),
                    "in_flight_messages": {
                        stream: len(messages)
                        for stream, messages in self._in_flight[group_name].items()
                    },
                    "failed_messages": {
                        stream: len(messages)
                        for stream, messages in self._failed_messages[
                            group_name
                        ].items()
                    },
                    "dlq_messages": {
                        stream: len(messages)
                        for stream, messages in self._dead_letter_queue[
                            group_name
                        ].items()
                    },
                }
                for group_name, group_info in self._consumer_groups.items()
            }
        }

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
