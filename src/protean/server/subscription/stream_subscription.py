import asyncio
import logging
import os
import secrets
import socket
from typing import TYPE_CHECKING, Dict, List, Optional, Union

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import ConfigurationError
from protean.port.broker import BaseBroker
from protean.utils import fqn
from protean.utils.eventing import Message

from . import BaseSubscription

if TYPE_CHECKING:
    from .profiles import SubscriptionConfig

logger = logging.getLogger(__name__)


class StreamSubscription(BaseSubscription):
    """
    Represents a subscription to a Redis Stream using blocking reads.

    A stream subscription allows a handler to receive and process messages from a specific stream
    using Redis Streams' blocking read capability. This provides efficient, low-latency message
    consumption without CPU-intensive polling.
    """

    def __init__(
        self,
        engine,
        stream_category: str,
        handler: Union[BaseEventHandler, BaseCommandHandler],
        messages_per_tick: Optional[int] = None,
        blocking_timeout_ms: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_delay_seconds: Optional[float] = None,
        enable_dlq: Optional[bool] = None,
    ) -> None:
        """
        Initialize the StreamSubscription object.

        Args:
            engine: The Protean engine instance.
            stream_category (str): The name of the stream to subscribe to.
            handler (Union[BaseEventHandler, BaseCommandHandler]): The event or command handler.
            messages_per_tick (int, optional): The number of messages to process per tick.
                Defaults to config value or 10.
            blocking_timeout_ms (int, optional): Timeout in milliseconds for blocking reads.
                Defaults to config value or 5000.
            max_retries (int, optional): Maximum number of retries before moving to DLQ.
                Defaults to config value or 3.
            retry_delay_seconds (float, optional): Delay between retries in seconds.
                Defaults to config value or 1.
            enable_dlq (bool, optional): Whether to use a dead letter queue.
                Defaults to config value or True.
        """
        # Get configuration from domain
        server_config = engine.domain.config.get("server", {})
        stream_config = server_config.get("stream_subscription", {})

        # Use provided values or fall back to config, then to hardcoded defaults
        resolved_messages_per_tick: int = (
            messages_per_tick
            if messages_per_tick is not None
            else int(server_config.get("messages_per_tick", 10))
        )
        resolved_blocking_timeout_ms: int = (
            blocking_timeout_ms
            if blocking_timeout_ms is not None
            else int(stream_config.get("blocking_timeout_ms", 5000))
        )
        resolved_max_retries: int = (
            max_retries
            if max_retries is not None
            else int(stream_config.get("max_retries", 3))
        )
        resolved_retry_delay_seconds: float = (
            retry_delay_seconds
            if retry_delay_seconds is not None
            else float(stream_config.get("retry_delay_seconds", 1))
        )
        resolved_enable_dlq: bool = (
            enable_dlq
            if enable_dlq is not None
            else bool(stream_config.get("enable_dlq", True))
        )

        # Use zero tick interval for blocking reads
        # The blocking read timeout will control the actual pacing
        super().__init__(engine, resolved_messages_per_tick, tick_interval=0)

        self.handler = handler
        self.subscriber_name = fqn(self.handler)
        self.subscriber_class_name = self.handler.__name__

        # Generate unique subscription ID
        self.subscription_id = self._generate_subscription_id()

        # Stream-specific attributes
        self.stream_category = stream_category
        self.blocking_timeout_ms: int = resolved_blocking_timeout_ms
        self.max_retries: int = resolved_max_retries
        self.retry_delay_seconds: float = resolved_retry_delay_seconds
        self.enable_dlq: bool = resolved_enable_dlq

        # Consumer name for Redis Streams (unique per consumer instance)
        self.consumer_name = self.subscription_id

        # Consumer group name (shared across consumers of same handler)
        self.consumer_group = self.subscriber_name

        # Dead letter queue stream name
        self.dlq_stream = f"{self.stream_category}:dlq"

        # Track retry counts for messages
        self.retry_counts: Dict[str, int] = {}

        # Get broker from domain
        self.broker: Optional[BaseBroker] = None

    @classmethod
    def from_config(
        cls,
        engine,
        stream_category: str,
        handler: Union[BaseEventHandler, BaseCommandHandler],
        config: "SubscriptionConfig",
    ) -> "StreamSubscription":
        """Create a StreamSubscription instance from a SubscriptionConfig.

        This factory method creates a StreamSubscription using configuration
        values from a SubscriptionConfig object. It validates that the config
        is appropriate for a stream subscription.

        Args:
            engine: The Protean engine instance.
            stream_category: The name of the stream to subscribe to.
            handler: The event or command handler.
            config: The subscription configuration object.

        Returns:
            A configured StreamSubscription instance.

        Raises:
            ConfigurationError: If config.subscription_type is not STREAM.

        Example:
            >>> config = SubscriptionConfig.from_profile(SubscriptionProfile.PRODUCTION)
            >>> subscription = StreamSubscription.from_config(
            ...     engine, "orders", OrderEventHandler, config
            ... )
        """
        # Import here to avoid circular imports
        from .profiles import SubscriptionType

        # Validate subscription type
        if config.subscription_type != SubscriptionType.STREAM:
            raise ConfigurationError(
                f"Cannot create StreamSubscription from config with "
                f"subscription_type={config.subscription_type.value}. "
                f"Expected subscription_type=stream."
            )

        return cls(
            engine=engine,
            stream_category=stream_category,
            handler=handler,
            messages_per_tick=config.messages_per_tick,
            blocking_timeout_ms=config.blocking_timeout_ms,
            max_retries=config.max_retries,
            retry_delay_seconds=config.retry_delay_seconds,
            enable_dlq=config.enable_dlq,
        )

    def _generate_subscription_id(self) -> str:
        """Generate a unique subscription ID."""
        hostname = socket.gethostname()
        pid = os.getpid()
        random_hex = secrets.token_hex(3)  # 3 bytes = 6 hex digits
        return f"{self.subscriber_class_name}-{hostname}-{pid}-{random_hex}"

    async def initialize(self) -> None:
        """
        Perform stream-specific initialization.

        This method gets the broker and ensures the consumer group exists.

        Raises:
            RuntimeError: If no default broker is configured

        Returns:
            None
        """
        # Get the default broker from domain
        # StreamSubscription always uses the default broker
        self.broker = self.engine.domain.brokers.get("default")
        if not self.broker:
            raise RuntimeError(
                f"No default broker configured for StreamSubscription {self.subscriber_name}"
            )

        # Ensure consumer group exists
        try:
            self.broker._ensure_group(self.consumer_group, self.stream_category)
        except Exception as e:
            logger.error(f"Failed to ensure consumer group {self.consumer_group}: {e}")
            raise

        logger.debug(
            f"Initialized subscription for {self.subscriber_name} "
            f"on stream '{self.stream_category}' with consumer group '{self.consumer_group}'"
        )

    async def poll(self) -> None:
        """
        High-performance continuous message processing loop.

        Uses blocking reads with no polling overhead for maximum efficiency.
        Implements backpressure by processing messages as fast as possible
        while yielding control periodically for other tasks.
        """
        batches_processed = 0

        while self.keep_going and not self.engine.shutting_down:
            try:
                # Blocking read - no CPU spinning
                messages = await self.get_next_batch_of_messages()

                if messages:
                    await self.process_batch(messages)
                    batches_processed += 1

                    # Yield control only after processing a batch
                    # This maximizes throughput while maintaining responsiveness
                    if batches_processed % 10 == 0:  # Yield every 10 batches
                        await asyncio.sleep(0)
                else:
                    # No messages available, the blocking read timed out
                    # This is normal, just yield control
                    await asyncio.sleep(0)

            except asyncio.CancelledError:
                logger.info(f"Subscription cancelled: {self.subscriber_name}")
                break
            except Exception as e:
                logger.exception(
                    f"Error processing messages for {self.subscriber_name}: {e}"
                )
                # Exponential backoff on errors
                await asyncio.sleep(
                    min(0.1 * (2 ** min(batches_processed % 5, 4)), 1.0)
                )

    async def get_next_batch_of_messages(self) -> List[tuple[str, dict]]:
        """
        Get the next batch of messages using blocking read.

        This method uses Redis Streams' XREADGROUP with BLOCK parameter to efficiently
        wait for new messages without polling.

        Returns:
            List[tuple[str, dict]]: The next batch of messages to process as (id, payload) tuples.
        """
        if not self.broker:
            logger.error("Broker not initialized")
            return []

        try:
            # Run the blocking Redis call in a thread pool to avoid blocking the event loop
            # This allows other async tasks to run concurrently
            messages = await asyncio.to_thread(
                self.broker.read_blocking,
                stream=self.stream_category,
                consumer_group=self.consumer_group,
                consumer_name=self.consumer_name,
                timeout_ms=self.blocking_timeout_ms,
                count=self.messages_per_tick,
            )

            return messages
        except Exception as e:
            logger.error(f"Error reading messages from stream: {e}")
            return []

    async def process_batch(self, messages: List[tuple[str, dict]]) -> int:
        """
        Process a batch of messages.

        This method takes a batch of messages and processes each message by calling the `handle_message` method
        of the engine. It handles retries and dead letter queue for failed messages.

        Args:
            messages (List[tuple[str, dict]]): The batch of messages to process as (id, payload) tuples.

        Returns:
            int: The number of messages processed successfully.
        """
        logger.debug(
            f"[{self.subscriber_class_name}] Received {len(messages)} message(s)"
        )
        successful_count = 0

        for identifier, payload in messages:
            message = await self._deserialize_message(identifier, payload)
            if not message:
                continue  # Message was moved to DLQ during deserialization

            assert message.metadata is not None, "Message metadata cannot be None"
            message_type = message.metadata.headers.type or "unknown"
            short_id = (message.metadata.headers.id or identifier)[:8]

            logger.info(
                f"[{self.subscriber_class_name}] Processing {message_type} "
                f"(ID: {short_id}...)"
            )

            # Process the message
            is_successful = await self.engine.handle_message(self.handler, message)

            if is_successful:
                if await self._acknowledge_message(identifier, message):
                    successful_count += 1
                    logger.info(
                        f"[{self.subscriber_class_name}] Completed {message_type} "
                        f"(ID: {short_id}...) — acked"
                    )
            else:
                logger.warning(
                    f"[{self.subscriber_class_name}] Failed {message_type} "
                    f"(ID: {short_id}...) — retrying"
                )
                await self.handle_failed_message(identifier, payload)

        return successful_count

    async def _deserialize_message(
        self, identifier: str, payload: dict
    ) -> Optional[Message]:
        """Deserialize a message payload, handling errors by moving to DLQ."""
        try:
            return Message.deserialize(payload)
        except Exception as e:
            logger.error(f"Deserialization failed for message {identifier}: {e}")
            await self.move_to_dlq(identifier, payload)
            return None

    async def _acknowledge_message(
        self, identifier: str, message: Optional[Message] = None
    ) -> bool:
        """Acknowledge successful message processing."""
        assert self.broker is not None, "Broker not initialized"
        ack_result = self.broker.ack(
            self.stream_category, identifier, self.consumer_group
        )
        if ack_result:
            # Clear retry count if exists
            self.retry_counts.pop(identifier, None)

            # Emit message.acked trace
            if message and message.metadata:
                self.engine.emitter.emit(
                    event="message.acked",
                    stream=self.stream_category,
                    message_id=message.metadata.headers.id or identifier,
                    message_type=message.metadata.headers.type or "unknown",
                    handler=self.subscriber_class_name,
                )

            return True
        else:
            logger.warning(f"Failed to acknowledge message {identifier}")
            return False

    async def handle_failed_message(self, identifier: str, payload: dict) -> None:
        """
        Handle a message that failed processing.

        Implements retry logic and moves to DLQ after max retries.

        Args:
            identifier (str): The message identifier
            payload (dict): The message payload
        """
        retry_count = self._increment_retry_count(identifier)

        if retry_count < self.max_retries:
            await self._retry_message(identifier, retry_count)
        else:
            await self._exhaust_retries(identifier, payload)

    def _increment_retry_count(self, identifier: str) -> int:
        """Increment and return the retry count for a message."""
        self.retry_counts[identifier] = self.retry_counts.get(identifier, 0) + 1
        return self.retry_counts[identifier]

    async def _retry_message(self, identifier: str, retry_count: int) -> None:
        """Retry a failed message after delay."""
        assert self.broker is not None, "Broker not initialized"
        logger.debug(
            f"Retrying message {identifier} (attempt {retry_count}/{self.max_retries}) "
            f"after {self.retry_delay_seconds}s delay"
        )

        # Emit message.nacked trace
        self.engine.emitter.emit(
            event="message.nacked",
            stream=self.stream_category,
            message_id=identifier,
            message_type="unknown",
            status="retry",
            handler=self.subscriber_class_name,
            metadata={"retry_count": retry_count, "max_retries": self.max_retries},
        )

        await asyncio.sleep(self.retry_delay_seconds)

        # NACK the message to make it available for reprocessing
        self.broker.nack(self.stream_category, identifier, self.consumer_group)

    async def _exhaust_retries(self, identifier: str, payload: dict) -> None:
        """Handle a message that has exhausted all retries."""
        assert self.broker is not None, "Broker not initialized"
        logger.warning(
            f"Message {identifier} exhausted retries ({self.max_retries} attempts), moving to DLQ"
        )
        await self.move_to_dlq(identifier, payload)

        # ACK the message to remove it from the pending list
        self.broker.ack(self.stream_category, identifier, self.consumer_group)

        # Clear retry count
        self.retry_counts.pop(identifier, None)

    async def move_to_dlq(self, identifier: str, payload: dict) -> None:
        """
        Move a failed message to the dead letter queue.

        Args:
            identifier (str): The original message identifier
            payload (dict): The message payload
        """
        if not self.enable_dlq:
            return

        assert self.broker is not None, "Broker not initialized"
        try:
            dlq_message = self._create_dlq_message(identifier, payload)
            self.broker.publish(self.dlq_stream, dlq_message)
            logger.info(f"Moved message {identifier} to DLQ stream {self.dlq_stream}")

            # Emit message.dlq trace
            message_type = (
                payload.get("metadata", {}).get("headers", {}).get("type", "unknown")
            )
            self.engine.emitter.emit(
                event="message.dlq",
                stream=self.stream_category,
                message_id=identifier,
                message_type=message_type,
                status="error",
                handler=self.subscriber_class_name,
                metadata={
                    "dlq_stream": self.dlq_stream,
                    "retry_count": self.retry_counts.get(identifier, self.max_retries),
                },
            )
        except Exception as e:
            logger.exception(f"Failed to move message {identifier} to DLQ: {e}")

    def _create_dlq_message(self, identifier: str, payload: dict) -> dict:
        """Create a DLQ message with failure metadata."""
        return {
            **payload,
            "_dlq_metadata": {
                "original_stream": self.stream_category,
                "original_id": identifier,
                "consumer_group": self.consumer_group,
                "consumer": self.consumer_name,
                "failed_at": payload.get("metadata", {}).get("headers", {}).get("time"),
                "retry_count": self.retry_counts.get(identifier, self.max_retries),
            },
        }

    async def cleanup(self) -> None:
        """
        Perform cleanup tasks during shutdown.

        This method clears any in-memory state during shutdown.

        Returns:
            None
        """
        # Clear retry counts
        self.retry_counts.clear()
        logger.debug(f"Cleanup completed for subscription: {self.subscriber_name}")
