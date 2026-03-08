import asyncio
import logging
import os
import secrets
import socket

from datetime import datetime, timezone
from typing import Dict, Type

from protean.core.subscriber import BaseSubscriber
from protean.port.broker import BaseBroker
from protean.utils import fqn

from . import BaseSubscription

logger = logging.getLogger(__name__)


class BrokerSubscription(BaseSubscription):
    """Subscription to a broker stream with retry tracking and dead letter queue.

    Reads messages from an external broker stream via a subscriber handler.
    Messages are acknowledged on success and retried on failure up to
    ``max_retries`` attempts. After exhausting retries, messages are routed
    to a dead letter queue (DLQ) if enabled.

    Error Handling
    ~~~~~~~~~~~~~~

    When a handler fails to process a message:

    1. **Retry count is incremented** — tracked in-memory per message identifier.
    2. **If retries remain** — the message is NACKed (returned to the broker for
       re-delivery) after a configurable delay. A ``message.nacked`` trace event
       is emitted.
    3. **If retries are exhausted** — the message is moved to a DLQ stream
       (``{stream_name}:dlq``), ACKed from the original stream, and a
       ``message.dlq`` trace event is emitted.

    When ``enable_dlq`` is ``False``, exhausted messages are simply ACKed and
    discarded (logged as a warning).

    Configuration
    ~~~~~~~~~~~~~

    All parameters can be set in ``domain.toml`` under
    ``[server.broker_subscription]``:

    - ``max_retries`` (default 3) — retry attempts before DLQ routing.
    - ``retry_delay_seconds`` (default 1) — delay between retries.
    - ``enable_dlq`` (default True) — set to False to discard exhausted messages.

    Per-handler overrides can be passed via the constructor.
    """

    def __init__(
        self,
        engine,
        broker,
        stream_name: str,
        handler: Type[BaseSubscriber],
        messages_per_tick: int = 10,
        tick_interval: int = 1,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
        enable_dlq: bool | None = None,
    ) -> None:
        """
        Initialize the BrokerSubscription object.

        Args:
            engine: The Protean engine instance.
            broker: The broker instance.
            stream_name: The name of the stream to subscribe to.
            handler: The subscriber handler.
            messages_per_tick: The number of messages to process per tick.
            tick_interval: The interval between ticks.
            max_retries: Maximum retry attempts before DLQ. None uses config default.
            retry_delay_seconds: Delay between retries. None uses config default.
            enable_dlq: Enable dead letter queue. None uses config default.
        """
        # Initialize parent class
        super().__init__(engine, messages_per_tick, tick_interval)

        self.handler = handler
        self.subscriber_name = fqn(self.handler)
        self.subscriber_class_name = handler.__name__

        # Generate unique subscription ID
        hostname = socket.gethostname()
        pid = os.getpid()
        random_hex = secrets.token_hex(3)  # 3 bytes = 6 hex digits
        self.subscription_id = (
            f"{self.subscriber_class_name}-{hostname}-{pid}-{random_hex}"
        )

        # Broker specific attributes
        self.broker: BaseBroker = broker
        self.stream_name = stream_name
        self.dlq_stream = f"{stream_name}:dlq"

        # Ensure consumer group exists for this stream
        self.broker._ensure_group(self.subscriber_name, self.stream_name)

        # Resolve retry/DLQ configuration from domain config
        server_config = engine.domain.config.get("server", {})
        bs_config = server_config.get("broker_subscription", {})

        self.max_retries: int = (
            max_retries
            if max_retries is not None
            else int(bs_config.get("max_retries", 3))
        )
        self.retry_delay_seconds: float = (
            retry_delay_seconds
            if retry_delay_seconds is not None
            else float(bs_config.get("retry_delay_seconds", 1))
        )
        self.enable_dlq: bool = (
            enable_dlq
            if enable_dlq is not None
            else bool(bs_config.get("enable_dlq", True))
        )

        # In-memory retry tracking (message identifier -> count)
        self.retry_counts: Dict[str, int] = {}

    async def get_next_batch_of_messages(self):
        """
        Get the next batch of messages to process.

        This method reads messages from the broker for the specified consumer group.
        It retrieves a specified number of messages per tick.

        Returns:
            List[tuple]: The next batch of messages to process as (identifier, payload) tuples.
        """
        messages = self.broker.read(
            self.stream_name,
            self.subscriber_name,  # Use subscriber_name as consumer group
            no_of_messages=self.messages_per_tick,
        )  # FIXME Implement filtering

        return messages

    async def process_batch(self, messages: list[dict]):
        """
        Process a batch of messages.

        This method takes a batch of messages and processes each message by calling
        the ``handle_broker_message`` method of the engine. On failure, messages are
        retried up to ``max_retries`` times before being routed to the DLQ.

        Args:
            messages: The batch of messages to process as (identifier, payload) tuples.

        Returns:
            int: The number of messages processed successfully.
        """
        logger.debug(f"Processing {len(messages)} messages...")
        successful_count = 0

        for message in messages:
            identifier, payload = message
            # Process the message and get a success/failure result
            is_successful = await self.engine.handle_broker_message(
                self.handler,
                payload,
                message_id=identifier,
                stream=self.stream_name,
                worker_id=self.subscription_id,
            )

            if is_successful:
                # Acknowledge successful processing
                ack_result = self.broker.ack(
                    self.stream_name, identifier, self.subscriber_name
                )
                if ack_result:
                    successful_count += 1
                    # Clear retry count on success
                    self.retry_counts.pop(identifier, None)
                else:
                    logger.warning(f"Failed to acknowledge message {identifier}")
            else:
                # Handle failure with retry/DLQ logic
                await self._handle_failed_message(identifier, payload)

        return successful_count

    # ──────────────────────────────────────────────────────────────────────
    # Retry / DLQ
    # ──────────────────────────────────────────────────────────────────────

    def _increment_retry_count(self, identifier: str) -> int:
        """Increment and return the retry count for a message."""
        self.retry_counts[identifier] = self.retry_counts.get(identifier, 0) + 1
        return self.retry_counts[identifier]

    async def _handle_failed_message(self, identifier: str, payload: dict) -> None:
        """Handle a message that failed processing.

        Increments the retry count and either retries (NACK) or exhausts
        (DLQ + ACK) based on the current count vs ``max_retries``.

        Args:
            identifier: The broker message identifier.
            payload: The message payload dict.
        """
        retry_count = self._increment_retry_count(identifier)

        if retry_count < self.max_retries:
            await self._retry_message(identifier, retry_count)
        else:
            await self._exhaust_retries(identifier, payload)

    async def _retry_message(self, identifier: str, retry_count: int) -> None:
        """Retry a failed message after a delay.

        NACKs the message so the broker re-delivers it on the next read.
        Emits a ``message.nacked`` trace event.

        Args:
            identifier: The broker message identifier.
            retry_count: The current retry attempt number.
        """
        logger.debug(
            f"[{self.subscriber_class_name}] Retrying message {identifier} "
            f"(attempt {retry_count}/{self.max_retries}) "
            f"after {self.retry_delay_seconds}s delay"
        )

        # Emit trace event
        self.engine.emitter.emit(
            event="message.nacked",
            stream=self.stream_name,
            message_id=identifier,
            message_type="unknown",
            status="retry",
            handler=self.subscriber_class_name,
            metadata={
                "retry_count": retry_count,
                "max_retries": self.max_retries,
            },
            worker_id=self.subscription_id,
        )

        if self.retry_delay_seconds > 0:
            await asyncio.sleep(self.retry_delay_seconds)

        # NACK to make the message available for reprocessing
        nack_result = self.broker.nack(
            self.stream_name, identifier, self.subscriber_name
        )
        if not nack_result:
            logger.warning(
                f"[{self.subscriber_class_name}] Failed to NACK message {identifier}"
            )

    async def _exhaust_retries(self, identifier: str, payload: dict) -> None:
        """Handle a message that has exhausted all retry attempts.

        Moves the message to the DLQ (if enabled), ACKs it from the original
        stream, and clears the retry count.

        Args:
            identifier: The broker message identifier.
            payload: The message payload dict.
        """
        logger.warning(
            f"[{self.subscriber_class_name}] Message {identifier} exhausted retries "
            f"({self.max_retries} attempts), "
            f"{'moving to DLQ' if self.enable_dlq else 'discarding'}"
        )

        if self.enable_dlq:
            await self._move_to_dlq(identifier, payload)

        # ACK to remove from pending
        self.broker.ack(self.stream_name, identifier, self.subscriber_name)

        # Clear retry count
        self.retry_counts.pop(identifier, None)

    async def _move_to_dlq(self, identifier: str, payload: dict) -> None:
        """Move a failed message to the dead letter queue.

        Publishes the message to the DLQ stream with enriched metadata
        and emits a ``message.dlq`` trace event.

        Args:
            identifier: The broker message identifier.
            payload: The message payload dict.
        """
        try:
            dlq_message = self._create_dlq_message(identifier, payload)
            self.broker.publish(self.dlq_stream, dlq_message)

            logger.info(
                f"[{self.subscriber_class_name}] Moved message {identifier} "
                f"to DLQ stream {self.dlq_stream}"
            )

            # Emit trace event
            message_type = (
                payload.get("metadata", {}).get("headers", {}).get("type", "unknown")
            )
            self.engine.emitter.emit(
                event="message.dlq",
                stream=self.stream_name,
                message_id=identifier,
                message_type=message_type,
                status="error",
                handler=self.subscriber_class_name,
                metadata={
                    "dlq_stream": self.dlq_stream,
                    "retry_count": self.retry_counts.get(identifier, self.max_retries),
                },
                worker_id=self.subscription_id,
            )
        except Exception as e:
            logger.exception(
                f"[{self.subscriber_class_name}] Failed to move message "
                f"{identifier} to DLQ: {e}"
            )

    def _create_dlq_message(self, identifier: str, payload: dict) -> dict:
        """Create a DLQ message with failure metadata.

        Preserves the original payload and adds a ``_dlq_metadata`` dict
        with provenance information.

        Args:
            identifier: The broker message identifier.
            payload: The original message payload.

        Returns:
            dict: The enriched DLQ message.
        """
        return {
            **payload,
            "_dlq_metadata": {
                "original_stream": self.stream_name,
                "original_id": identifier,
                "consumer_group": self.subscriber_name,
                "consumer": self.subscription_id,
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "retry_count": self.retry_counts.get(identifier, self.max_retries),
            },
        }
