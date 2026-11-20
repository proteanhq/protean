import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from protean.infra.registry import brokers
from protean.port.broker import (
    DLQ_SUFFIX,
    BrokerCapabilities,
    BrokerHealth,
    BrokerMessage,
    BrokerPort,
    ConsumerGroupInfo,
    DeadLetterQueuePort,
    DLQEntry,
    dlq_metadata,
    failure_time,
    newest_failure_first,
    parse_dlq_entry,
    require_aware_cutoff,
)

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

# Constants
CONSUMER_GROUP_SEPARATOR = ":"
MAX_RETRIES = 3
RETRY_DELAY = 1.0
BACKOFF_MULTIPLIER = 2.0
# Cap the backoff delay. A subscription-owned stream has no nack ceiling, so its
# broker-side retry count can grow without bound, and ``backoff_multiplier`` is
# configurable; either can make ``backoff_multiplier ** retry_count`` overflow
# the float (2.0 ** 1024 raises OverflowError) and freeze the message.
MAX_BACKOFF_DELAY = 3600.0
MESSAGE_TIMEOUT = 300.0
ENABLE_DLQ = True
OPERATION_STATE_TTL_MAX = 60.0


class OperationState(Enum):
    """Track the state of ack/nack operations for idempotency"""

    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    NACKED = "nacked"
    FAILED = "failed"


class InlineBroker(DeadLetterQueuePort):
    broker_type = "inline"

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        # A copy: the broker never writes to the configuration it was given.
        self.config: Mapping[str, Any] = dict(config)

        # The inline broker always delivers in the publishing process.
        self.is_async = False

        # Configuration for retry behavior and timeouts
        self._max_retries = int(self.config.get("max_retries", MAX_RETRIES))
        self._retry_delay = float(self.config.get("retry_delay", RETRY_DELAY))
        self._backoff_multiplier = float(
            self.config.get("backoff_multiplier", BACKOFF_MULTIPLIER)
        )
        self._message_timeout = float(
            self.config.get("message_timeout", MESSAGE_TIMEOUT)
        )  # 5 minutes default
        self._enable_dlq = bool(self.config.get("enable_dlq", ENABLE_DLQ))
        self._operation_state_ttl = max(
            int(self._message_timeout * 3), OPERATION_STATE_TTL_MAX
        )  # At least 1 minute

        # Messages per stream, in arrival order, as (identifier, message) pairs
        self._messages: defaultdict[str, list[tuple[str, dict[str, Any]]]] = (
            defaultdict(list)
        )

        # Consumer groups keyed by "stream:group_name". Each holds the set of
        # consumers and the time the group was created.
        self._consumer_groups: dict[str, dict[str, Any]] = {}

        # In-flight messages keyed by "stream:consumer_group", then by message
        # identifier. Each entry is (identifier, message, delivery timestamp).
        self._in_flight: defaultdict[
            str, dict[str, tuple[str, dict[str, Any], float]]
        ] = defaultdict(dict)

        # Nacked messages waiting for retry, keyed by "stream:consumer_group".
        # Each entry is (identifier, message, retry count, next retry time).
        self._failed_messages: defaultdict[
            str, list[tuple[str, dict[str, Any], int, float]]
        ] = defaultdict(list)

        # Nacked messages due for redelivery, keyed by "stream:consumer_group".
        # They wait here, not in the stream, so a retry adds no copy that
        # other groups would read and DLQ counts would include.
        self._redeliveries: defaultdict[str, list[tuple[str, dict[str, Any]]]] = (
            defaultdict(list)
        )

        # Retry count per message identifier, keyed by "stream:consumer_group"
        self._retry_counts: defaultdict[str, dict[str, int]] = defaultdict(dict)

        # Read position per "stream:consumer_group", so several groups can read
        # one stream independently
        self._consumer_positions: defaultdict[str, int] = defaultdict(int)

        # Which consumer groups own each message, keyed by message identifier
        self._message_ownership: defaultdict[str, dict[str, bool]] = defaultdict(dict)

        # Operation state and its timestamp per message identifier, keyed by
        # consumer group, for idempotency
        self._operation_states: defaultdict[
            str, dict[str, tuple[OperationState, float]]
        ] = defaultdict(dict)

        # Track group keys owned by a Protean subscription. For these, nack
        # holds and redelivers with no independent ceiling; the subscription
        # owns retry and dead-lettering via {stream}:dlq. Entries are
        # "stream:consumer_group" keys.
        self._subscription_owned_groups: set[str] = set()

    @property
    def capabilities(self) -> BrokerCapabilities:
        """InlineBroker provides full manual broker capabilities for testing."""
        return (
            BrokerCapabilities.RELIABLE_MESSAGING | BrokerCapabilities.DEAD_LETTER_QUEUE
        )

    def publish(self, stream: str, message: dict[str, Any]) -> str:
        """Publish a message dict to the stream"""
        # We always generate a new identifier for inline broker, since
        #   there is underlying persistence layer to generate identifiers.
        identifier = str(uuid.uuid4())

        # Store message as tuple (identifier, message)
        self._messages[stream].append((identifier, message))

        return identifier

    def read(
        self,
        stream: str,
        consumer_group: str,
        limit: int,
        *,
        new_messages: bool = False,
    ) -> list[BrokerMessage]:
        """Read up to ``limit`` messages the group has not received yet.

        The inline broker hands a message to a group once and redelivers a
        nacked one to that group alone, so ``new_messages`` makes no
        difference here.
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

    def _next_message(self, stream: str, consumer_group: str) -> BrokerMessage | None:
        """Deliver the next message in ``stream`` to ``consumer_group``, if any."""

        # Create combined group key for this stream+consumer_group
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"

        # Clean up stale in-flight messages first
        self._cleanup_stale_messages(consumer_group, self._message_timeout)

        # First, check for any failed messages that are ready for retry
        self._requeue_failed_messages(stream, consumer_group)

        redeliveries = self._redeliveries[group_key]
        if redeliveries:
            identifier, message = redeliveries.pop(0)
            return self._deliver(stream, consumer_group, identifier, message)

        # Check current position for this consumer group
        position = self._consumer_positions[group_key]

        # Check if there's a message at this position
        if position < len(self._messages[stream]):
            identifier, message = self._messages[stream][position]

            # Increment position for this consumer group
            self._consumer_positions[group_key] += 1

            return self._deliver(stream, consumer_group, identifier, message)

        # There is no message in the stream for this consumer group
        return None

    def _deliver(
        self,
        stream: str,
        consumer_group: str,
        identifier: str,
        message: dict[str, Any],
    ) -> BrokerMessage:
        """Hand ``identifier`` to ``consumer_group`` and hold it in flight."""
        # Track message ownership
        self._message_ownership[identifier][consumer_group] = True

        # Clear any previous operation state for fresh processing
        self._clear_operation_state(consumer_group, identifier)

        # Move message to in-flight status
        self._store_in_flight_message(stream, consumer_group, identifier, message)

        return BrokerMessage(identifier, message)

    def ack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        """Template method for message acknowledgment with common logic"""
        try:
            # Clean up expired operation states first
            self._cleanup_expired_operation_states()

            # Check for idempotency
            current_state = self._get_operation_state(consumer_group, message_id)
            if current_state == OperationState.ACKNOWLEDGED:
                logger.debug(
                    f"Message '{message_id}' already acknowledged by consumer group '{consumer_group}' (idempotent)"
                )
                return False
            elif current_state == OperationState.NACKED:
                # In consistent behavior with Redis Streams, a NACKed message can still be ACKed
                # NACK just means the message stays pending and can be processed again
                logger.debug(
                    f"Message '{message_id}' was previously nacked, now acknowledging (similar to Redis Streams behavior)"
                )
                # Continue with ACK processing - don't return False

            # Validate consumer group exists
            if not self._validate_consumer_group(consumer_group):
                logger.warning(f"Consumer group '{consumer_group}' does not exist")
                return False

            # Validate message ownership
            if not self._validate_message_ownership(message_id, consumer_group):
                logger.warning(
                    f"Message '{message_id}' was not delivered to consumer group '{consumer_group}'"
                )
                return False

            # Check if message is still in-flight
            # For NACKed messages, they might be in failed messages queue instead
            if not self._is_in_flight_message(stream, consumer_group, message_id):
                if current_state == OperationState.NACKED:
                    # For NACKed messages, check if it's in failed messages and move it back to in-flight for ACK
                    if self._handle_nacked_message_for_ack(
                        stream, consumer_group, message_id
                    ):
                        logger.debug(
                            f"Moved NACKed message '{message_id}' back to in-flight for acknowledgment"
                        )
                    else:
                        logger.warning(
                            f"NACKed message '{message_id}' not found in failed messages for consumer group '{consumer_group}'"
                        )
                        return False
                else:
                    logger.warning(
                        f"Message '{message_id}' not found in in-flight status for consumer group '{consumer_group}'"
                    )
                    return False

            # Set operation state to acknowledged
            self._store_operation_state(
                consumer_group, message_id, OperationState.ACKNOWLEDGED
            )

            # Remove message from in-flight status
            self._remove_in_flight_message(stream, consumer_group, message_id)

            # Clean up retry count tracking
            self._remove_retry_count(stream, consumer_group, message_id)

            # Remove any failed message entry
            self._remove_failed_message(stream, consumer_group, message_id)

            # Clean up message ownership tracking (broker-specific implementation)
            self._cleanup_message_ownership(message_id, consumer_group)

            # Log successful acknowledgment (non-critical operation)
            try:
                logger.debug(
                    f"Message '{message_id}' acknowledged by consumer group '{consumer_group}'"
                )
            except Exception:
                # Logging failure shouldn't cause ACK to fail
                logger.exception(
                    "broker.inline.ack_log_failed", extra={"identifier": message_id}
                )
                # Clean up operation state since we can't reliably track the operation
                self._clear_operation_state(consumer_group, message_id)
                return False

            return True

        except Exception:  # ack reports False on any failure and clears state; logged
            logger.exception(
                "broker.inline.ack_failed", extra={"identifier": message_id}
            )
            # Clean up operation state on failure
            self._clear_operation_state(consumer_group, message_id)
            return False

    def nack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        """Template method for negative acknowledgment with common logic"""
        try:
            # Clean up expired operation states first
            self._cleanup_expired_operation_states()

            # Check for idempotency
            current_state = self._get_operation_state(consumer_group, message_id)
            if current_state == OperationState.NACKED:
                logger.debug(
                    f"Message '{message_id}' already nacked by consumer group '{consumer_group}' (idempotent)"
                )
                return False
            elif current_state == OperationState.ACKNOWLEDGED:
                logger.warning(
                    f"Cannot nack message '{message_id}' - already acknowledged by consumer group '{consumer_group}'"
                )
                return False

            # Validate consumer group exists
            if not self._validate_consumer_group(consumer_group):
                logger.warning(f"Consumer group '{consumer_group}' does not exist")
                return False

            # Validate message ownership
            if not self._validate_message_ownership(message_id, consumer_group):
                logger.warning(
                    f"Message '{message_id}' was not delivered to consumer group '{consumer_group}'"
                )
                return False

            # Get message from in-flight status
            message_data = self._get_in_flight_message(
                stream, consumer_group, message_id
            )
            if not message_data:
                logger.warning(
                    f"Message '{message_id}' not found in in-flight status for consumer group '{consumer_group}'"
                )
                return False

            _, message = message_data

            # Get current retry count and increment it
            retry_count = self._get_retry_count(stream, consumer_group, message_id)
            new_retry_count = retry_count + 1

            group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            if (
                new_retry_count <= self._max_retries
                or group_key in self._subscription_owned_groups
            ):
                return self._handle_nack_with_retry(
                    stream,
                    message_id,
                    consumer_group,
                    message,
                    retry_count,
                    new_retry_count,
                )
            else:
                return self._handle_nack_max_retries_exceeded(
                    stream, message_id, consumer_group, message, new_retry_count
                )

        except Exception:  # nack reports False on any failure and clears state; logged
            logger.exception(
                "broker.inline.nack_failed", extra={"identifier": message_id}
            )
            # Clean up operation state on failure
            self._clear_operation_state(consumer_group, message_id)
            return False

    def _handle_nack_with_retry(
        self,
        stream: str,
        identifier: str,
        consumer_group: str,
        message: dict[str, Any],
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

            # Calculate next retry time with exponential backoff. A retry delay
            # of zero stays zero at every retry count: the exponentiation would
            # overflow long before it is multiplied by zero. For a real delay,
            # saturate at MAX_BACKOFF_DELAY so neither an unbounded owned-stream
            # retry count nor a large configured multiplier can overflow the
            # exponentiation or balloon the wall-clock wait.
            if self._retry_delay <= 0:
                delay = 0.0
            else:
                try:
                    delay = min(
                        self._retry_delay * (self._backoff_multiplier**retry_count),
                        MAX_BACKOFF_DELAY,
                    )
                except OverflowError:
                    delay = MAX_BACKOFF_DELAY
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
            except Exception:
                # Logging failure shouldn't cause NACK to fail
                logger.exception(
                    "broker.inline.nack_log_failed", extra={"identifier": identifier}
                )

            return True

        except Exception:  # retry setup reports False and clears state; logged
            logger.exception(
                "broker.inline.nack_retry_failed", extra={"identifier": identifier}
            )
            self._clear_operation_state(consumer_group, identifier)
            return False

    def _handle_nack_max_retries_exceeded(
        self,
        stream: str,
        identifier: str,
        consumer_group: str,
        message: dict[str, Any],
        new_retry_count: int,
    ) -> bool:
        """Handle nack when max retries exceeded"""
        try:
            # Set operation state to failed
            self._store_operation_state(
                consumer_group, identifier, OperationState.FAILED
            )

            # Max retries exceeded - move to DLQ or discard. The message
            # leaves in-flight only after the DLQ write, so a write that
            # raises leaves it in flight for the timeout path to expire again.
            if self._enable_dlq:
                self._store_dlq_message(
                    stream,
                    consumer_group,
                    identifier,
                    message,
                    "max_retries_exceeded",
                    new_retry_count,
                )
                logger.warning(
                    f"Message '{identifier}' moved to DLQ after {self._max_retries} retries"
                )
            else:
                logger.warning(
                    f"Message '{identifier}' discarded after {self._max_retries} retries"
                )

            self._remove_in_flight_message(stream, consumer_group, identifier)

            # Clean up tracking
            self._remove_retry_count(stream, consumer_group, identifier)
            self._remove_failed_message(stream, consumer_group, identifier)
            self._cleanup_message_ownership(identifier, consumer_group)

            return True

        except Exception:  # discard step reports False and clears state; logged
            logger.exception(
                "broker.inline.max_retries_failed", extra={"identifier": identifier}
            )
            self._clear_operation_state(consumer_group, identifier)
            return False

    def _requeue_failed_messages(self, stream: str, consumer_group: str) -> None:
        """Move failed messages back to the main queue if they're ready for retry"""
        try:
            ready_messages = self._get_retry_ready_messages(stream, consumer_group)
            if ready_messages:
                self._requeue_messages(stream, consumer_group, ready_messages)
        except Exception:  # a failed requeue must not stop message reads; logged
            logger.exception(
                "broker.inline.requeue_failed",
                extra={"consumer_group": consumer_group, "stream": stream},
            )

    # Manual broker implementation methods
    def _store_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str, message: dict[str, Any]
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
    ) -> tuple[str, dict[str, Any]] | None:
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
        message: dict[str, Any],
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
    ) -> list[tuple[str, dict[str, Any]]]:
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
        message: dict[str, Any],
        failure_reason: str,
        retry_count: int,
    ) -> None:
        """Publish a message to ``{stream}:dlq`` with a ``_dlq_metadata`` record.

        The record has the keys the engine writes when it dead-letters a
        message, except ``consumer``, plus ``failure_reason``.
        """
        dlq_message = {
            **message,
            "_dlq_metadata": {
                "original_stream": stream,
                "original_id": identifier,
                "consumer_group": consumer_group,
                "failure_reason": failure_reason,
                "failed_at": self.domain.clock.now().isoformat(),
                "retry_count": retry_count,
            },
        }
        self.publish(f"{stream}{DLQ_SUFFIX}", dlq_message)

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
        group_suffix = f"{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        matching_group_keys = [
            group_key
            for group_key in self._in_flight
            if group_key.endswith(group_suffix)
        ]

        for group_key in matching_group_keys:
            # Recover the stream by stripping the exact consumer-group suffix.
            # A stream name can itself contain the separator (aggregate
            # categories are ``domain::aggregate``, DLQ streams are
            # ``{stream}:dlq``), so splitting on the first separator would
            # yield a truncated stream and strand the message under a group
            # key nothing reads.
            stream = group_key[: -len(group_suffix)]

            _cleanup_stale_group(
                self, group_key, stream, consumer_group, cutoff_time, current_time
            )

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
        self,
        stream: str,
        consumer_group: str,
        messages: list[tuple[str, dict[str, Any]]],
    ) -> None:
        """Queue ``messages`` for redelivery to ``consumer_group`` before its
        next unread message."""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self._redeliveries[group_key].extend(messages)

    def _cleanup_message_ownership(self, identifier: str, consumer_group: str) -> None:
        """Clean up message ownership tracking"""
        if identifier in self._message_ownership:
            if consumer_group in self._message_ownership[identifier]:
                del self._message_ownership[identifier][consumer_group]
            if not self._message_ownership[identifier]:
                del self._message_ownership[identifier]

    def _handle_nacked_message_for_ack(
        self, stream: str, consumer_group: str, identifier: str
    ) -> bool:
        """Handle acknowledging a previously NACKed message by moving it back to in-flight"""
        try:
            group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            failed_messages = self._failed_messages[group_key]

            # Find the message in failed messages
            for i, (msg_id, message, _retry_count, _next_retry_time) in enumerate(
                failed_messages
            ):
                if msg_id == identifier:
                    # Remove from failed messages
                    del failed_messages[i]

                    # Move back to in-flight for acknowledgment
                    self._store_in_flight_message(
                        stream, consumer_group, identifier, message
                    )

                    return True

            return False
        except Exception:  # a failed nack lookup reports False; logged with traceback
            logger.exception(
                "broker.inline.nack_handle_failed", extra={"identifier": identifier}
            )
            return False

    def _cleanup_expired_operation_states(self) -> None:
        """Clean up expired operation states"""
        current_time = time.time()
        cutoff_time = current_time - self._operation_state_ttl

        for consumer_group in list(self._operation_states.keys()):
            for identifier in list(self._operation_states[consumer_group].keys()):
                _state, timestamp = self._operation_states[consumer_group][identifier]
                if timestamp < cutoff_time:
                    del self._operation_states[consumer_group][identifier]

            # Clean up empty consumer group entries
            if not self._operation_states[consumer_group]:
                del self._operation_states[consumer_group]

    # ------------------------------------------------------------------
    # DLQ Management
    # ------------------------------------------------------------------

    def dlq_list(self, dlq_streams: list[str], limit: int = 100) -> list[DLQEntry]:
        """Return up to ``limit`` entries from ``dlq_streams``, newest failure first."""
        entries = [
            parse_dlq_entry(dlq_stream, identifier, message)
            for dlq_stream in dlq_streams
            for identifier, message in self._messages.get(dlq_stream, [])
        ]
        return newest_failure_first(entries)[:limit]

    def dlq_get(self, dlq_stream: str, dlq_id: str) -> DLQEntry | None:
        """Return the entry ``dlq_id`` in ``dlq_stream``, or ``None`` if there is none."""
        for identifier, message in self._messages.get(dlq_stream, []):
            if identifier == dlq_id:
                return parse_dlq_entry(dlq_stream, identifier, message)
        return None

    def dlq_replay(self, dlq_stream: str, dlq_id: str, target_stream: str) -> bool:
        """Publish the entry ``dlq_id`` to ``target_stream`` without its
        ``_dlq_metadata``, and remove it."""
        for index, (identifier, message) in enumerate(
            self._messages.get(dlq_stream, [])
        ):
            if identifier == dlq_id:
                self.publish(target_stream, _without_dlq_metadata(message))
                self._remove_dlq_entries(dlq_stream, {index})
                logger.info(
                    f"Replayed DLQ message '{identifier}' to stream '{target_stream}'"
                )
                return True
        return False

    def dlq_replay_all(self, dlq_stream: str, target_stream: str) -> int:
        """Publish every entry in ``dlq_stream`` to ``target_stream`` without its
        ``_dlq_metadata``, and remove it.

        When a publication raises, removes the entries published before it
        and keeps the rest in ``dlq_stream``.
        """
        published: set[int] = set()
        try:
            # ``publish`` only appends, so the indices stay valid even when
            # ``target_stream`` is ``dlq_stream``.
            for index, (_identifier, message) in enumerate(
                list(self._messages.get(dlq_stream, []))
            ):
                self.publish(target_stream, _without_dlq_metadata(message))
                published.add(index)
        finally:
            self._remove_dlq_entries(dlq_stream, published)
        return len(published)

    def dlq_purge(self, dlq_stream: str) -> int:
        """Remove every entry in ``dlq_stream``."""
        entries = self._messages.get(dlq_stream, [])
        return self._remove_dlq_entries(dlq_stream, set(range(len(entries))))

    def dlq_trim(self, dlq_stream: str, older_than: datetime) -> int:
        """Remove the entries in ``dlq_stream`` that failed before ``older_than``.

        Keeps an entry whose ``_dlq_metadata.failed_at`` is missing, cannot be
        parsed, or has no time zone, since it cannot be compared with
        ``older_than``.

        Raises:
            TypeError: ``older_than`` is not a ``datetime``.
            ValueError: ``older_than`` has no time zone.
        """
        require_aware_cutoff(older_than)
        expired = {
            index
            for index, (_identifier, message) in enumerate(
                self._messages.get(dlq_stream, [])
            )
            if _failed_before(message, older_than)
        }
        return self._remove_dlq_entries(dlq_stream, expired)

    def dlq_depth(self, dlq_stream: str) -> int:
        """Return the number of entries in ``dlq_stream``."""
        return len(self._messages.get(dlq_stream, []))

    def _remove_dlq_entries(self, dlq_stream: str, indices: set[int]) -> int:
        """Delete the entries at ``indices`` from ``dlq_stream`` and return how many.

        For each consumer group that reads ``dlq_stream``, lowers its read
        position by the number of removed entries before it, so the group's
        next read returns the entry it would have read next. The group also
        forgets the removed entries it holds in flight or waiting for retry,
        so a later ``nack`` cannot put a removed entry back.
        """
        entries = self._messages.get(dlq_stream)
        if not entries or not indices:
            return 0

        removed_ids = {entries[index][0] for index in indices}
        self._messages[dlq_stream] = [
            entry for index, entry in enumerate(entries) if index not in indices
        ]
        for consumer_group in self._groups_reading(dlq_stream):
            group_key = f"{dlq_stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
            position = self._consumer_positions[group_key]
            self._consumer_positions[group_key] = position - sum(
                1 for index in indices if index < position
            )
            for identifier in removed_ids:
                self._forget_message(dlq_stream, consumer_group, identifier)
        return len(indices)

    def _groups_reading(self, stream: str) -> list[str]:
        """Return the names of the consumer groups created on ``stream``."""
        return [
            record["group"]
            for record in self._consumer_groups.values()
            if record["stream"] == stream
        ]

    def _forget_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Drop every record ``consumer_group`` keeps of ``identifier`` on ``stream``."""
        self._remove_in_flight_message(stream, consumer_group, identifier)
        self._remove_failed_message(stream, consumer_group, identifier)
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self._redeliveries[group_key] = [
            entry for entry in self._redeliveries[group_key] if entry[0] != identifier
        ]
        self._remove_retry_count(stream, consumer_group, identifier)
        self._cleanup_message_ownership(identifier, consumer_group)
        self._clear_operation_state(consumer_group, identifier)

    def create_group(self, stream: str, consumer_group: str) -> None:
        """Create ``consumer_group`` on ``stream`` if it does not exist."""
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        if group_key not in self._consumer_groups:
            # The stream and the group are kept apart because either name can
            # contain the separator, so the key alone cannot be split back.
            self._consumer_groups[group_key] = {
                "stream": stream,
                "group": consumer_group,
                "consumers": set(),
                "created_at": time.time(),
            }

    def mark_subscription_owned(self, stream: str, consumer_group: str) -> None:
        """Record that a subscription owns retry/DLQ for this group.

        For an owned (stream, consumer group), ``nack`` bypasses the broker's
        own retry ceiling and always holds-and-redelivers, so the broker never
        moves the message to its native DLQ. The subscription is the single
        retry/DLQ authority and publishes exhausted messages to ``{stream}:dlq``.
        """
        group_key = f"{stream}{CONSUMER_GROUP_SEPARATOR}{consumer_group}"
        self._subscription_owned_groups.add(group_key)

    def consumer_groups(self) -> dict[str, ConsumerGroupInfo]:
        """Return each consumer group by name, across all streams.

        ``pending`` is the number of messages delivered to the group and not
        yet acknowledged or nacked, summed over the group's streams.
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

            consumer_groups_info[consumer_group]["pending"] += len(
                self._in_flight[group_key]
            )

        return consumer_groups_info

    def clear(self) -> None:
        """Flush all data in broker instance.

        ``_subscription_owned_groups`` is deliberately kept: it records which
        groups a live subscription owns retry/DLQ for, which is wiring set once
        at subscription init, not message data. Clearing it here would silently
        reinstate the broker's nack ceiling for a still-alive subscription.
        """
        self._messages.clear()
        self._consumer_groups.clear()
        self._in_flight.clear()
        self._failed_messages.clear()
        self._redeliveries.clear()
        self._retry_counts.clear()
        self._consumer_positions.clear()
        self._message_ownership.clear()
        self._operation_states.clear()

    def ping(self) -> bool:
        """Test connectivity to the inline broker.

        Since InlineBroker is in-memory, it's always available.

        Returns:
            bool: Always True for inline broker
        """
        return True

    def health(self) -> BrokerHealth:
        """Return message counts, consumer groups and configuration.

        The inline broker is in memory, so it always reports itself healthy.
        """
        # Calculate total messages across all streams
        total_messages = sum(len(messages) for messages in self._messages.values())

        # Calculate total in-flight messages across all consumer groups
        total_in_flight = sum(len(in_flight) for in_flight in self._in_flight.values())

        # Calculate total failed messages across all consumer groups
        total_failed = sum(len(failed) for failed in self._failed_messages.values())

        # Count the messages in the ``{stream}:dlq`` streams, which
        # ``total_messages`` also counts
        total_dlq = sum(
            len(messages)
            for stream, messages in self._messages.items()
            if stream.endswith(DLQ_SUFFIX)
        )

        # Get unique streams and consumer groups
        streams = set(self._messages.keys())
        consumer_groups = set()
        for group_key in self._consumer_groups:
            if CONSUMER_GROUP_SEPARATOR in group_key:
                _, group_name = group_key.rsplit(CONSUMER_GROUP_SEPARATOR, 1)
                consumer_groups.add(group_name)

        # Calculate memory usage estimate (rough approximation)
        memory_estimate = (
            (total_messages - total_dlq) * 100  # Rough estimate per message
            + total_in_flight * 150  # In-flight messages have more metadata
            + total_failed * 150  # Failed messages have retry info
            + total_dlq * 150  # DLQ messages have failure info
        )

        return BrokerHealth(
            healthy=True,
            message_counts={
                "total_messages": total_messages,
                "in_flight": total_in_flight,
                "failed": total_failed,
                "dlq": total_dlq,
            },
            consumer_groups={
                "count": len(consumer_groups),
                "names": list(consumer_groups),
            },
            details={
                "streams": {"count": len(streams), "names": list(streams)},
                "memory_estimate_bytes": memory_estimate,
                "configuration": {
                    "max_retries": self._max_retries,
                    "retry_delay": self._retry_delay,
                    "message_timeout": self._message_timeout,
                    "enable_dlq": self._enable_dlq,
                },
            },
        )

    def get_connection(self) -> object:
        """Return ``None``: the inline broker holds no client."""
        return None

    def reconnect(self) -> bool:
        """Ensure connection to the inline broker.

        Since InlineBroker is in-memory, no external connection is needed.

        Returns:
            bool: Always True for inline broker
        """
        return True


def _cleanup_stale_group(
    broker: InlineBroker,
    group_key: str,
    stream: str,
    consumer_group: str,
    cutoff_time: float,
    current_time: float,
) -> None:
    """Take each message in-flight under ``group_key`` since before
    ``cutoff_time`` out of flight, and hold it for redelivery or expire it."""
    owned = group_key in broker._subscription_owned_groups

    for identifier, (_msg_id, message, timestamp) in list(
        broker._in_flight[group_key].items()
    ):
        if timestamp < cutoff_time:
            if owned:
                _hold_stale_message(
                    broker,
                    group_key,
                    stream,
                    consumer_group,
                    identifier,
                    message,
                    current_time,
                )
            else:
                _expire_stale_message(
                    broker, stream, consumer_group, identifier, message
                )

            # Removed after the DLQ write, so a write that raises leaves the
            # message in flight for the next cleanup to expire again.
            del broker._in_flight[group_key][identifier]


def _hold_stale_message(
    broker: InlineBroker,
    group_key: str,
    stream: str,
    consumer_group: str,
    identifier: str,
    message: dict[str, Any],
    current_time: float,
) -> None:
    # A subscription owns retry/DLQ for this group, so the
    # broker must not dead-letter underneath it. Hold the
    # timed-out message for redelivery (it stays available
    # via the failed-message retry path) instead of moving
    # it to the native DLQ. Retry count is preserved.
    retry_count = broker._retry_counts[group_key].get(identifier, 0)
    broker._remove_failed_message(stream, consumer_group, identifier)
    broker._store_failed_message(
        stream,
        consumer_group,
        identifier,
        message,
        retry_count,
        current_time,
    )


def _expire_stale_message(
    broker: InlineBroker,
    stream: str,
    consumer_group: str,
    identifier: str,
    message: dict[str, Any],
) -> None:
    # Move to DLQ if enabled
    if broker._enable_dlq:
        broker._store_dlq_message(
            stream,
            consumer_group,
            identifier,
            message,
            "timeout",
            broker._get_retry_count(stream, consumer_group, identifier),
        )
        logger.warning(f"Message '{identifier}' moved to DLQ due to timeout")

    # Clean up tracking
    broker._remove_retry_count(stream, consumer_group, identifier)
    broker._cleanup_message_ownership(identifier, consumer_group)


def _without_dlq_metadata(message: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in message.items() if key != "_dlq_metadata"}


def _failed_before(message: dict[str, Any], older_than: datetime) -> bool:
    """Return ``True`` when the message's ``failed_at`` is earlier than ``older_than``.

    Returns ``False`` when the message has no usable ``failed_at``.
    """
    failed_time = failure_time(dlq_metadata(message).get("failed_at"))
    return failed_time is not None and failed_time < older_than


# Self-registration function for entry point
def register() -> None:
    """Register InlineBroker with Protean.

    InlineBroker is always available as it has no external dependencies.
    """
    brokers.register("inline", "protean.adapters.broker.inline.InlineBroker")


_PORT_CHECK: type[BrokerPort] = InlineBroker
_DLQ_PORT_CHECK: type[DeadLetterQueuePort] = InlineBroker
