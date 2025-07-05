from __future__ import annotations

import logging
import logging.config
import time
from abc import ABCMeta, abstractmethod
from collections import defaultdict
from enum import Enum
from typing import TYPE_CHECKING, Type

from protean.core.subscriber import BaseSubscriber
from protean.exceptions import ValidationError
from protean.utils import Processing

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1.0
BACKOFF_MULTIPLIER = 2.0
MESSAGE_TIMEOUT = 300.0
ENABLE_DLQ = True
OPERATION_STATE_TTL_MAX = 60.0


class OperationState(Enum):
    """Track the state of ack/nack operations for idempotency"""

    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    NACKED = "nacked"
    FAILED = "failed"


class BaseBroker(metaclass=ABCMeta):
    """This class outlines the base broker functions, to be satisfied by all implementing brokers.

    It is also a marker interface for registering broker classes with the domain"""

    # FIXME Replace with typing.Protocol

    def __init__(
        self, name: str, domain: "Domain", conn_info: dict[str, str | bool]
    ) -> None:
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

        self._subscribers = defaultdict(set)
        self._last_ping_time = None
        self._last_ping_success = None
        self._start_time = time.time()

    def publish(self, stream: str, message: dict) -> str:
        """Publish a message to the broker.

        Args:
            stream (str): The stream to which the message should be published
            message (dict): The message payload to be published

        Returns:
            str: The identifier of the message. The content of the identifier is broker-specific.
            All brokers are guaranteed to provide message identifiers.

        Raises:
            ValidationError: If message is an empty dict
        """
        if not message:
            raise ValidationError({"message": ["Message cannot be empty"]})

        try:
            identifier = self._publish(stream, message)
        except Exception as e:
            # Check if this is a connection-related error and attempt recovery
            if self._is_connection_error(e):
                logger.warning(f"Connection error during publish: {e}")
                if self._ensure_connection():
                    # Retry the operation once after reconnection
                    identifier = self._publish(stream, message)
                else:
                    raise
            else:
                raise

        if (
            self.domain.config["message_processing"] == Processing.SYNC.value
            and self._subscribers[stream]
        ):
            for subscriber_cls in self._subscribers[stream]:
                subscriber = subscriber_cls()
                subscriber(message)

        return identifier

    def ping(self) -> bool:
        """Test broker connectivity.

        Returns:
            bool: True if broker is reachable and responsive, False otherwise
        """
        try:
            start_time = time.time()
            result = self._ping()
            self._last_ping_time = time.time() - start_time
            self._last_ping_success = result
            return result
        except Exception as e:
            logger.debug(f"Ping failed for broker {self.name}: {e}")
            self._last_ping_time = None
            self._last_ping_success = False
            return False

    def health_stats(self) -> dict:
        """Get comprehensive health statistics for the broker.

        Returns:
            dict: Health statistics with the following structure:
                {
                    'status': 'healthy' | 'degraded' | 'unhealthy',
                    'connected': bool,
                    'last_ping_ms': float | None,
                    'uptime_seconds': float,
                    'details': dict  # Broker-specific details
                }
        """
        try:
            # Get broker-specific health details
            broker_details = self._health_stats()

            # Perform a fresh ping to get current connectivity status
            is_connected = self.ping()

            # Determine overall health status
            if is_connected and broker_details.get("healthy", True):
                status = "healthy"
            elif is_connected:
                status = "degraded"  # Connected but some issues reported
            else:
                status = "unhealthy"

            # Calculate uptime since broker initialization
            uptime_seconds = time.time() - self._start_time

            return {
                "status": status,
                "connected": is_connected,
                "last_ping_ms": self._last_ping_time * 1000
                if self._last_ping_time is not None
                else None,
                "uptime_seconds": uptime_seconds,
                "details": broker_details,
            }
        except Exception as e:
            logger.error(f"Error gathering health stats for broker {self.name}: {e}")
            return {
                "status": "unhealthy",
                "connected": False,
                "last_ping_ms": None,
                "uptime_seconds": 0,
                "details": {"error": str(e)},
            }

    def ensure_connection(self) -> bool:
        """Ensure broker connection is healthy, attempt reconnection if needed.

        This method can be called explicitly or is triggered automatically
        when connection-related exceptions are encountered.

        Returns:
            bool: True if connection is healthy/restored, False otherwise
        """
        return self._ensure_connection()

    def _is_connection_error(self, exception: Exception) -> bool:
        """Check if an exception indicates a connection-related error.

        Args:
            exception: The exception to analyze

        Returns:
            bool: True if this appears to be a connection error
        """
        # Default implementation checks for common connection error patterns
        error_str = str(exception).lower()
        connection_indicators = [
            "connection",
            "timeout",
            "timed out",
            "network",
            "unreachable",
            "refused",
            "reset",
            "broken pipe",
            "socket",
        ]
        return any(indicator in error_str for indicator in connection_indicators)

    @abstractmethod
    def _ping(self) -> bool:
        """Test basic connectivity to the broker.

        Returns:
            bool: True if broker responds successfully, False otherwise
        """

    @abstractmethod
    def _health_stats(self) -> dict:
        """Get broker-specific health and performance statistics.

        Returns:
            dict: Broker-specific health details. Common fields may include:
                - 'healthy': bool (overall broker health)
                - 'queue_depth': int (pending messages)
                - 'consumer_lag': dict (lag per consumer group)
                - 'error_rate': float (recent error percentage)
                - Any other broker-specific metrics
        """

    @abstractmethod
    def _ensure_connection(self) -> bool:
        """Ensure connection to broker is healthy, reconnect if necessary.

        Returns:
            bool: True if connection is healthy/restored, False if unable to connect
        """

    @abstractmethod
    def _publish(self, stream: str, message: dict) -> str:
        """Overidden method to publish a message with payload to the configured broker.

        Args:
            stream (str): The stream to which the message should be published
            message (dict): The message payload to be published

        Returns:
            str: The identifier of the message. The content of the identifier is broker-specific.
            All brokers must return a non-empty string identifier.
        """

    def get_next(self, stream: str, consumer_group: str) -> dict | None:
        """Retrieve the next message to process from broker.

        Args:
            stream (str): The stream from which to retrieve the message
            consumer_group (str): The consumer group identifier

        Returns:
            dict: The message payload, or None if no messages available
        """
        try:
            return self._get_next(stream, consumer_group)
        except Exception as e:
            # Check if this is a connection-related error and attempt recovery
            if self._is_connection_error(e):
                logger.warning(f"Connection error during get_next: {e}")
                if self._ensure_connection():
                    # Retry the operation once after reconnection
                    return self._get_next(stream, consumer_group)
                else:
                    raise
            else:
                raise

    @abstractmethod
    def _get_next(self, stream: str, consumer_group: str) -> dict | None:
        """Overridden method to retrieve the next message to process from broker."""

    def read(
        self, stream: str, consumer_group: str, no_of_messages: int
    ) -> list[tuple[str, dict]]:
        """Read messages from the broker.

        Args:
            stream (str): The stream from which to read messages
            consumer_group (str): The consumer group identifier
            no_of_messages (int): The number of messages to read

        Returns:
            list[tuple[str, dict]]: The list of (identifier, message) tuples
        """
        try:
            return self._read(stream, consumer_group, no_of_messages)
        except Exception as e:
            # Check if this is a connection-related error and attempt recovery
            if self._is_connection_error(e):
                logger.warning(f"Connection error during read: {e}")
                if self._ensure_connection():
                    # Retry the operation once after reconnection
                    return self._read(stream, consumer_group, no_of_messages)
                else:
                    raise
            else:
                raise

    def ack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Acknowledge successful processing of a message.

        Args:
            stream (str): The stream from which the message was received
            identifier (str): The unique identifier of the message to acknowledge
            consumer_group (str): The consumer group that processed the message

        Returns:
            bool: True if the message was successfully acknowledged, False otherwise
        """
        try:
            return self._ack(stream, identifier, consumer_group)
        except Exception as e:
            # Check if this is a connection-related error and attempt recovery
            if self._is_connection_error(e):
                logger.warning(f"Connection error during ack: {e}")
                if self._ensure_connection():
                    # Retry the operation once after reconnection
                    return self._ack(stream, identifier, consumer_group)
                else:
                    raise
            else:
                raise

    def nack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Negative acknowledge - mark message for reprocessing.

        Args:
            stream (str): The stream from which the message was received
            identifier (str): The unique identifier of the message to nack
            consumer_group (str): The consumer group that failed to process the message

        Returns:
            bool: True if the message was successfully marked for reprocessing, False otherwise
        """
        try:
            return self._nack(stream, identifier, consumer_group)
        except Exception as e:
            # Check if this is a connection-related error and attempt recovery
            if self._is_connection_error(e):
                logger.warning(f"Connection error during nack: {e}")
                if self._ensure_connection():
                    # Retry the operation once after reconnection
                    return self._nack(stream, identifier, consumer_group)
                else:
                    raise
            else:
                raise

    @abstractmethod
    def _read(
        self, stream: str, consumer_group: str, no_of_messages: int
    ) -> list[tuple[str, dict]]:
        """Read messages from the broker.

        Args:
            stream (str): The stream from which to read messages
            consumer_group (str): The consumer group identifier
            no_of_messages (int): The number of messages to read

        Returns:
            list[tuple[str, dict]]: The list of (identifier, message) tuples
        """

    @abstractmethod
    def _ack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Acknowledge successful processing of a message.

        Args:
            stream (str): The stream from which the message was received
            identifier (str): The unique identifier of the message to acknowledge
            consumer_group (str): The consumer group that processed the message

        Returns:
            bool: True if the message was successfully acknowledged, False otherwise
        """

    @abstractmethod
    def _nack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Negative acknowledge - mark message for reprocessing.

        Args:
            stream (str): The stream from which the message was received
            identifier (str): The unique identifier of the message to nack
            consumer_group (str): The consumer group that failed to process the message

        Returns:
            bool: True if the message was successfully marked for reprocessing, False otherwise
        """

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all data in broker instance.

        Useful for clearing cache and running tests.
        """

    @abstractmethod
    def _ensure_group(self, group_name: str, stream: str = None) -> None:
        """Bootstrap/create consumer group.

        Args:
            group_name (str): The name of the consumer group to create
            stream (str, optional): The stream name for brokers that require it (e.g., Redis Streams)
        """

    def info(self) -> dict:
        """Get information about consumer groups and consumers in each group.

        Returns:
            dict: Information about consumer groups and their consumers
        """
        return self._info()

    @abstractmethod
    def _info(self) -> dict:
        """Overridden method to provide information about consumer groups and consumers.

        Returns:
            dict: Information about consumer groups and their consumers
        """

    def register(self, subscriber_cls: Type[BaseSubscriber]) -> None:
        """Registers subscribers to brokers against their streams.

        Arguments:
            subscriber_cls {Subscriber} -- The subscriber class connected to the stream
        """
        stream = subscriber_cls.meta_.stream

        self._subscribers[stream].add(subscriber_cls)

        logger.debug(
            f"Broker {self.name}: Registered Subscriber {subscriber_cls.__name__} for stream {stream}"
        )


class BaseManualBroker(BaseBroker):
    """Base class for brokers that require manual message tracking and retry handling.

    This class provides common functionality for brokers like InlineBroker and RedisPubSubBroker
    that need to manually track message states, implement retry logic, and handle DLQ operations.

    Brokers with native consumer group support (like Redis Streams, Kafka) should inherit
    directly from BaseBroker instead.
    """

    def __init__(
        self, name: str, domain: "Domain", conn_info: dict[str, str | bool]
    ) -> None:
        super().__init__(name, domain, conn_info)

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

    # Abstract methods for broker-specific storage operations
    @abstractmethod
    def _store_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str, message: dict
    ) -> None:
        """Store a message in in-flight status"""

    @abstractmethod
    def _remove_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove a message from in-flight status"""

    @abstractmethod
    def _is_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> bool:
        """Check if a message is in in-flight status"""

    @abstractmethod
    def _get_in_flight_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> tuple[str, dict] | None:
        """Get in-flight message data"""

    @abstractmethod
    def _store_operation_state(
        self, consumer_group: str, identifier: str, state: OperationState
    ) -> None:
        """Store operation state for idempotency"""

    @abstractmethod
    def _get_operation_state(
        self, consumer_group: str, identifier: str
    ) -> OperationState | None:
        """Get current operation state"""

    @abstractmethod
    def _clear_operation_state(self, consumer_group: str, identifier: str) -> None:
        """Clear operation state"""

    @abstractmethod
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

    @abstractmethod
    def _remove_failed_message(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove a failed message from retry queue"""

    @abstractmethod
    def _get_retry_ready_messages(
        self, stream: str, consumer_group: str
    ) -> list[tuple[str, dict]]:
        """Get messages ready for retry and remove them from failed queue"""

    @abstractmethod
    def _store_dlq_message(
        self,
        stream: str,
        consumer_group: str,
        identifier: str,
        message: dict,
        failure_reason: str,
    ) -> None:
        """Store a message in Dead Letter Queue"""

    @abstractmethod
    def _validate_consumer_group(self, consumer_group: str) -> bool:
        """Validate that the consumer group exists"""

    @abstractmethod
    def _validate_message_ownership(self, identifier: str, consumer_group: str) -> bool:
        """Validate that the message was delivered to the specified consumer group"""

    @abstractmethod
    def _cleanup_stale_messages(
        self, consumer_group: str, timeout_seconds: float
    ) -> None:
        """Remove messages that have been in-flight too long"""

    @abstractmethod
    def _get_retry_count(
        self, stream: str, consumer_group: str, identifier: str
    ) -> int:
        """Get current retry count for a message"""

    @abstractmethod
    def _set_retry_count(
        self, stream: str, consumer_group: str, identifier: str, count: int
    ) -> None:
        """Set retry count for a message"""

    @abstractmethod
    def _remove_retry_count(
        self, stream: str, consumer_group: str, identifier: str
    ) -> None:
        """Remove retry count tracking for a message"""

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

            logger.debug(
                f"Message '{identifier}' nacked, retry {new_retry_count}/{self._max_retries} in {delay:.2f}s"
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

    @abstractmethod
    def _requeue_messages(
        self, stream: str, consumer_group: str, messages: list[tuple[str, dict]]
    ) -> None:
        """Broker-specific implementation of requeuing messages"""

    @abstractmethod
    def _cleanup_message_ownership(self, identifier: str, consumer_group: str) -> None:
        """Clean up message ownership tracking"""

    @abstractmethod
    def _cleanup_expired_operation_states(self) -> None:
        """Clean up expired operation states"""

    def get_dlq_messages(self, consumer_group: str, stream: str = None) -> dict:
        """Get messages from Dead Letter Queue for inspection"""
        return self._get_dlq_messages(consumer_group, stream)

    @abstractmethod
    def _get_dlq_messages(self, consumer_group: str, stream: str = None) -> dict:
        """Broker-specific implementation of getting DLQ messages"""

    def reprocess_dlq_message(
        self, identifier: str, consumer_group: str, stream: str
    ) -> bool:
        """Move a message from DLQ back to the main queue for reprocessing"""
        return self._reprocess_dlq_message(identifier, consumer_group, stream)

    @abstractmethod
    def _reprocess_dlq_message(
        self, identifier: str, consumer_group: str, stream: str
    ) -> bool:
        """Broker-specific implementation of reprocessing DLQ messages"""

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

            logger.debug(
                f"Message '{identifier}' acknowledged by consumer group '{consumer_group}'"
            )
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
