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

from enum import Flag, auto

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


class BrokerCapabilities(Flag):
    # Tier 1: Universal Foundation (Every broker has these)
    PUBLISH = auto()  # Send messages
    SUBSCRIBE = auto()  # Receive messages

    # Tier 2: Storage & Consumer Management (Independent capabilities)
    CONSUMER_GROUPS = auto()  # Multiple consumers, load balancing

    # Tier 3: Message Lifecycle (Depends on CONSUMER_GROUPS)
    ACK_NACK = auto()  # Acknowledge successful/failed processing
    DELIVERY_GUARANTEES = auto()  # At-least-once delivery (depends on ACK_NACK)
    MESSAGE_ORDERING = auto()  # Preserve message order (can be independent)

    # Tier 4: Advanced Features (Various dependencies)
    DEAD_LETTER_QUEUE = auto()  # Handle failed messages (depends on ACK_NACK)
    REPLAY = auto()  # Re-read historical messages (depends on PERSISTENCE)
    STREAM_PARTITIONING = auto()  # Partition streams for scalability

    # Convenience Capability Sets
    BASIC_PUBSUB = PUBLISH | SUBSCRIBE

    SIMPLE_QUEUING = BASIC_PUBSUB | CONSUMER_GROUPS

    RELIABLE_MESSAGING = SIMPLE_QUEUING | ACK_NACK | DELIVERY_GUARANTEES

    ORDERED_MESSAGING = RELIABLE_MESSAGING | MESSAGE_ORDERING

    ENTERPRISE_STREAMING = (
        ORDERED_MESSAGING | DEAD_LETTER_QUEUE | REPLAY | STREAM_PARTITIONING
    )


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

    @property
    @abstractmethod
    def capabilities(self) -> BrokerCapabilities:
        """Return the capabilities of this broker implementation.

        Returns:
            BrokerCapabilities: The capabilities supported by this broker
        """

    def has_capability(self, capability: BrokerCapabilities) -> bool:
        """Check if broker has a specific capability.

        Args:
            capability: The capability to check for

        Returns:
            bool: True if the broker has the capability, False otherwise
        """
        return capability in self.capabilities

    def has_all_capabilities(self, capabilities: BrokerCapabilities) -> bool:
        """Check if broker has all the specified capabilities.

        Args:
            capabilities: The capabilities to check for

        Returns:
            bool: True if the broker has all capabilities, False otherwise
        """
        return (self.capabilities & capabilities) == capabilities

    def has_any_capability(self, capabilities: BrokerCapabilities) -> bool:
        """Check if broker has any of the specified capabilities.

        Args:
            capabilities: The capabilities to check for

        Returns:
            bool: True if the broker has any of the capabilities, False otherwise
        """
        return bool(self.capabilities & capabilities)

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
        # Check if broker supports consumer groups
        if not self.has_capability(BrokerCapabilities.CONSUMER_GROUPS):
            logger.warning(f"Broker {self.name} does not support consumer groups")
            return None

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
        # Check if broker supports consumer groups
        if not self.has_capability(BrokerCapabilities.CONSUMER_GROUPS):
            logger.warning(f"Broker {self.name} does not support consumer groups")
            return []

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
        # Check if broker supports acknowledgment
        if not self.has_capability(BrokerCapabilities.ACK_NACK):
            logger.warning(
                f"Broker {self.name} does not support message acknowledgment"
            )
            return False

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
        # Check if broker supports negative acknowledgment
        if not self.has_capability(BrokerCapabilities.ACK_NACK):
            logger.warning(
                f"Broker {self.name} does not support message negative acknowledgment"
            )
            return False

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
