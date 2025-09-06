import asyncio
import logging
import os
import secrets
import socket
from typing import Dict, List, Optional, Union

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.port.broker import BaseBroker
from protean.utils import fqn
from protean.utils.eventing import Message

from . import BaseSubscription

logger = logging.getLogger(__name__)


class StreamSubscription(BaseSubscription):
    """
    Represents a subscription to a Redis Stream using blocking reads.

    A stream subscription allows a handler to receive and process messages from a specific stream
    using Redis Streams' blocking read capability. This provides efficient, low-latency message
    consumption without CPU-intensive polling.
    """

    # Default configuration constants
    DEFAULT_MESSAGES_PER_TICK = 10
    DEFAULT_BLOCKING_TIMEOUT_MS = 5000
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY_SECONDS = 1
    DEFAULT_ENABLE_DLQ = True

    def __init__(
        self,
        engine,
        stream_category: str,
        handler: Union[BaseEventHandler, BaseCommandHandler],
        messages_per_tick: int = DEFAULT_MESSAGES_PER_TICK,
        blocking_timeout_ms: int = DEFAULT_BLOCKING_TIMEOUT_MS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay_seconds: int = DEFAULT_RETRY_DELAY_SECONDS,
        enable_dlq: bool = DEFAULT_ENABLE_DLQ,
    ) -> None:
        """
        Initialize the StreamSubscription object.

        Args:
            engine: The Protean engine instance.
            stream_category (str): The name of the stream to subscribe to.
            handler (Union[BaseEventHandler, BaseCommandHandler]): The event or command handler.
            messages_per_tick (int, optional): The number of messages to process per tick. Defaults to 10.
            blocking_timeout_ms (int, optional): Timeout in milliseconds for blocking reads. Defaults to 5000.
            max_retries (int, optional): Maximum number of retries before moving to DLQ. Defaults to 3.
            retry_delay_seconds (int, optional): Delay between retries in seconds. Defaults to 1.
            enable_dlq (bool, optional): Whether to use a dead letter queue. Defaults to True.
        """
        # Since blocking reads handle their own timing, we use tick_interval=0
        # to let the blocking read control the pacing
        super().__init__(engine, messages_per_tick, tick_interval=0)

        self.handler = handler
        self.subscriber_name = fqn(self.handler)
        self.subscriber_class_name = self.handler.__name__

        # Generate unique subscription ID
        self.subscription_id = self._generate_subscription_id()

        # Stream-specific attributes
        self.stream_category = stream_category
        self.blocking_timeout_ms = blocking_timeout_ms
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.enable_dlq = enable_dlq

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

        logger.info(
            f"Initialized StreamSubscription for {self.subscriber_name} "
            f"on stream {self.stream_category}"
        )

    async def poll(self) -> None:
        """
        Override poll to use blocking reads instead of sleep-based polling.

        This method continuously reads messages using blocking mode, which is more
        efficient than periodic polling.

        Returns:
            None
        """
        while self.keep_going and not self.engine.shutting_down:
            # Use blocking read to get messages
            messages = await self.get_next_batch_of_messages()
            if messages:
                await self.process_batch(messages)

            # In test mode, yield control briefly to allow shutdown
            if self.engine.test_mode:
                await asyncio.sleep(0)

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
            messages = self.broker.read_blocking(
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
        logger.debug(f"Processing {len(messages)} messages...")
        successful_count = 0

        for identifier, payload in messages:
            message = await self._deserialize_message(identifier, payload)
            if not message:
                continue  # Message was moved to DLQ during deserialization

            logger.info(
                f"{message.metadata.headers.type}-{message.metadata.headers.id} : {message.to_dict()}"
            )

            # Process the message
            is_successful = await self.engine.handle_message(self.handler, message)

            if is_successful:
                if await self._acknowledge_message(identifier):
                    successful_count += 1
            else:
                await self.handle_failed_message(identifier, payload)

        return successful_count

    async def _deserialize_message(
        self, identifier: str, payload: dict
    ) -> Optional[Message]:
        """Deserialize a message payload, handling errors by moving to DLQ."""
        try:
            return Message.deserialize(payload)
        except Exception as e:
            logger.error(
                f"Failed to deserialize message {identifier}: {e}. Moving to DLQ."
            )
            await self.move_to_dlq(identifier, payload)
            return None

    async def _acknowledge_message(self, identifier: str) -> bool:
        """Acknowledge successful message processing."""
        ack_result = self.broker.ack(
            self.stream_category, identifier, self.consumer_group
        )
        if ack_result:
            # Clear retry count if exists
            self.retry_counts.pop(identifier, None)
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
        logger.warning(
            f"Message {identifier} failed (attempt {retry_count}/{self.max_retries}). "
            f"Retrying after {self.retry_delay_seconds}s..."
        )
        await asyncio.sleep(self.retry_delay_seconds)

        # NACK the message to make it available for reprocessing
        self.broker.nack(self.stream_category, identifier, self.consumer_group)

    async def _exhaust_retries(self, identifier: str, payload: dict) -> None:
        """Handle a message that has exhausted all retries."""
        logger.error(
            f"Message {identifier} failed after {self.max_retries} attempts. "
            f"Moving to DLQ..."
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

        try:
            dlq_message = self._create_dlq_message(identifier, payload)
            self.broker.publish(self.dlq_stream, dlq_message)
            logger.info(f"Moved message {identifier} to DLQ stream {self.dlq_stream}")
        except Exception as e:
            logger.error(f"Failed to move message {identifier} to DLQ: {e}")

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
        logger.debug(f"Cleaned up StreamSubscription for {self.subscriber_name}")
