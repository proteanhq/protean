import asyncio
import logging
import os
import secrets
import socket
import time
from typing import TYPE_CHECKING, Any

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import ConfigurationError
from protean.port.broker import BaseBroker
from protean.utils import fqn
from protean.utils.eventing import Message
from protean.utils.telemetry import get_domain_metrics

from . import BaseSubscription
from .profiles import CircuitBreakerState

if TYPE_CHECKING:
    from protean.server.engine import Engine

    from .profiles import SubscriptionConfig

logger = logging.getLogger(__name__)

# When the breaker is OPEN and still inside its reset window, ``poll()`` sleeps
# in short slices rather than one long block so shutdown stays responsive.
_CIRCUIT_OPEN_SLEEP_CAP_SECONDS = 1.0


class StreamSubscription(BaseSubscription):
    """
    Represents a subscription to a Redis Stream using blocking reads.

    A stream subscription allows a handler to receive and process messages from a specific stream
    using Redis Streams' blocking read capability. This provides efficient, low-latency message
    consumption without CPU-intensive polling.

    When priority lanes are enabled, the subscription reads from two streams:
    - Primary stream (e.g., ``customer``): Production traffic, always drained first.
    - Backfill stream (e.g., ``customer:backfill``): Migration/bulk traffic, read only
      when the primary stream is empty.

    This ensures production events are always processed before backfill events.
    """

    def __init__(
        self,
        engine: "Engine",
        stream_category: str,
        handler: type[BaseEventHandler | BaseCommandHandler],
        messages_per_tick: int | None = None,
        blocking_timeout_ms: int | None = None,
        max_retries: int | None = None,
        retry_delay_seconds: float | None = None,
        enable_dlq: bool | None = None,
        circuit_breaker_threshold: int | None = None,
        circuit_breaker_reset_seconds: float | None = None,
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
            circuit_breaker_threshold (int, optional): Consecutive handler
                failures that trip the circuit breaker OPEN. Defaults to config
                value or 10.
            circuit_breaker_reset_seconds (float, optional): Seconds an OPEN
                breaker waits before allowing a single HALF_OPEN probe.
                Defaults to config value or 60.
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
        resolved_circuit_breaker_threshold: int = (
            circuit_breaker_threshold
            if circuit_breaker_threshold is not None
            else int(stream_config.get("circuit_breaker_threshold", 10))
        )
        resolved_circuit_breaker_reset_seconds: float = (
            circuit_breaker_reset_seconds
            if circuit_breaker_reset_seconds is not None
            else float(stream_config.get("circuit_breaker_reset_seconds", 60))
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

        # Circuit breaker: gates reads when the handler keeps failing. The
        # breaker counts consecutive handler-outcome failures, which is a
        # separate concern from poll()'s consecutive_errors backoff (that
        # covers broker/read exceptions). All state is in-memory per instance.
        self.circuit_breaker_threshold: int = resolved_circuit_breaker_threshold
        self.circuit_breaker_reset_seconds: float = (
            resolved_circuit_breaker_reset_seconds
        )
        self.circuit_state: CircuitBreakerState = CircuitBreakerState.CLOSED
        self.consecutive_handler_failures: int = 0
        self.circuit_opened_at: float | None = None

        # Consumer name for Redis Streams (unique per consumer instance)
        self.consumer_name = self.subscription_id

        # Consumer group name (shared across consumers of same handler)
        self.consumer_group = self.subscriber_name

        # Dead letter queue stream name
        self.dlq_stream = f"{self.stream_category}:dlq"

        # Track retry counts for messages
        self.retry_counts: dict[str, int] = {}

        # Get broker from domain
        self.broker: BaseBroker | None = None

        # Priority lanes configuration
        lanes_config = server_config.get("priority_lanes", {})
        self._lanes_enabled = lanes_config.get("enabled", False)
        self._backfill_suffix = lanes_config.get("backfill_suffix", "backfill")
        self.backfill_stream = f"{self.stream_category}:{self._backfill_suffix}"
        self.backfill_dlq_stream = f"{self.backfill_stream}:dlq"

        # Default stream used when callers don't provide an explicit stream
        # (e.g. standard mode where only one stream exists).
        self._default_stream = self.stream_category

    @classmethod
    def from_config(
        cls,
        engine: "Engine",
        stream_category: str,
        handler: type[BaseEventHandler | BaseCommandHandler],
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
        from .profiles import SubscriptionType  # noqa: PLC0415

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
            circuit_breaker_threshold=config.circuit_breaker_threshold,
            circuit_breaker_reset_seconds=config.circuit_breaker_reset_seconds,
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
        When priority lanes are enabled, also creates a consumer group for
        the backfill stream.

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

        # Ensure consumer group exists for primary stream
        try:
            self.broker._ensure_group(self.consumer_group, self.stream_category)
        except Exception as e:
            logger.error(f"Failed to ensure consumer group {self.consumer_group}: {e}")
            raise

        # Clean up stale consumers from previous engine runs
        try:
            removed = self.broker._cleanup_stale_consumers(
                self.stream_category, self.consumer_group, self.subscription_id
            )
            if removed > 0:
                logger.info(
                    f"Cleaned up {removed} stale consumer(s) for "
                    f"{self.subscriber_name} on '{self.stream_category}'"
                )
        except Exception:
            pass  # Non-critical — don't fail startup over cleanup

        # If priority lanes are enabled, also ensure consumer group for backfill stream
        if self._lanes_enabled:
            try:
                self.broker._ensure_group(self.consumer_group, self.backfill_stream)
            except Exception as e:
                logger.error(
                    f"Failed to ensure backfill consumer group "
                    f"{self.consumer_group} on {self.backfill_stream}: {e}"
                )
                raise

            # Clean up stale consumers on backfill stream too
            try:
                removed = self.broker._cleanup_stale_consumers(
                    self.backfill_stream, self.consumer_group, self.subscription_id
                )
                if removed > 0:
                    logger.info(
                        f"Cleaned up {removed} stale consumer(s) for "
                        f"{self.subscriber_name} on '{self.backfill_stream}'"
                    )
            except Exception:
                pass

            logger.debug(
                f"Initialized priority lanes for {self.subscriber_name}: "
                f"primary='{self.stream_category}', backfill='{self.backfill_stream}'"
            )

        logger.debug(
            f"Initialized subscription for {self.subscriber_name} "
            f"on stream '{self.stream_category}' with consumer group '{self.consumer_group}'"
        )

    async def poll(self) -> None:
        """
        High-performance continuous message processing loop.

        When priority lanes are disabled (default), uses standard blocking reads
        on the single stream.

        When priority lanes are enabled, implements a two-lane priority system:
        1. Non-blocking read on primary stream (production traffic)
        2. If messages found → process them, loop back to step 1
        3. If primary is empty → blocking read on backfill stream (short timeout)
        4. Process backfill messages, loop back to step 1

        This ensures production events are always processed before backfill events.
        The backfill blocking timeout is capped at 1 second so we re-check the
        primary stream frequently.
        """
        batches_processed = 0
        consecutive_errors = 0

        while self.keep_going and not self.engine.shutting_down:
            try:
                # Circuit breaker gate: an OPEN breaker pauses reads (shared by
                # both lanes-mode and standard-mode) so pending messages stay in
                # the stream/PEL for redelivery. Never acks an unprocessed message.
                if not await self._circuit_permits_reads():
                    continue

                if self._lanes_enabled:
                    # PRIORITY LANES MODE
                    # Step 1: Non-blocking read on primary (production) stream
                    messages = await self._read_primary_nonblocking()

                    if messages:
                        await self.process_batch(messages, stream=self.stream_category)
                        batches_processed += 1
                        # Loop back immediately to check primary again
                        if batches_processed % 10 == 0:
                            await asyncio.sleep(0)
                        consecutive_errors = 0
                        continue

                    # Step 2: Primary empty → blocking read on backfill stream
                    messages = await self._read_backfill_blocking()

                    if messages:
                        await self.process_batch(messages, stream=self.backfill_stream)
                        batches_processed += 1

                    # Yield control before re-checking primary
                    await asyncio.sleep(0)
                else:
                    # STANDARD MODE: unchanged behavior
                    messages = await self.get_next_batch_of_messages()

                    if messages:
                        await self.process_batch(messages, stream=self.stream_category)
                        batches_processed += 1

                        # Yield control only after processing a batch
                        # This maximizes throughput while maintaining responsiveness
                        if batches_processed % 10 == 0:  # Yield every 10 batches
                            await asyncio.sleep(0)
                    else:
                        # No messages available, the blocking read timed out
                        # This is normal, just yield control
                        await asyncio.sleep(0)

                consecutive_errors = 0

            except asyncio.CancelledError:
                logger.info(f"Subscription cancelled: {self.subscriber_name}")
                break
            except Exception as e:
                consecutive_errors += 1
                logger.exception(
                    f"Error in subscription {self.subscriber_name} "
                    f"(attempt {consecutive_errors}): {e}"
                )
                # Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
                backoff = min(2 ** (consecutive_errors - 1), 30)
                await asyncio.sleep(backoff)

    async def _circuit_permits_reads(self) -> bool:
        """Decide whether the circuit breaker allows a read this loop turn.

        Shared by both lanes-mode and standard-mode reads.

        - CLOSED / HALF_OPEN → reads are permitted.
        - OPEN and still inside the reset window → reads are paused. Sleeps for
          the remaining window (capped so shutdown stays responsive) and returns
          ``False`` so the caller skips this turn. No message is read or acked,
          so pending messages remain for redelivery.
        - OPEN and the reset window has elapsed → transition to HALF_OPEN and
          permit a single probe read.

        Returns:
            True if a read may proceed this turn, False if it must be skipped.
        """
        if self.circuit_state != CircuitBreakerState.OPEN:
            return True

        # OPEN: honor the reset window before allowing a probe.
        opened_at = self.circuit_opened_at
        if opened_at is not None:
            remaining = self.circuit_breaker_reset_seconds - (
                time.monotonic() - opened_at
            )
            if remaining > 0:
                await asyncio.sleep(min(remaining, _CIRCUIT_OPEN_SLEEP_CAP_SECONDS))
                return False

        # Reset window elapsed → allow a single HALF_OPEN probe.
        self._transition_to_half_open()
        return True

    def _current_batch_size(self) -> int:
        """Effective read count for this turn.

        A HALF_OPEN breaker probes with a single message so one outcome decides
        whether to close or re-open. Otherwise the configured tick size is used.
        """
        if self.circuit_state == CircuitBreakerState.HALF_OPEN:
            return 1
        return self.messages_per_tick

    def _record_handler_outcome(self, is_successful: bool) -> None:
        """Advance the circuit breaker from a single handler outcome.

        Called once per message in ``process_batch`` after the handler result is
        known. A message routed to the DLQ still counts as one failure here.

        Args:
            is_successful: The handler outcome for the message (independent of
                the broker ACK result).
        """
        if is_successful:
            self.consecutive_handler_failures = 0
            if self.circuit_state == CircuitBreakerState.HALF_OPEN:
                self._close_circuit()
            return

        self.consecutive_handler_failures += 1
        if self.circuit_state == CircuitBreakerState.HALF_OPEN:
            # A failing probe re-opens the breaker and restarts the timer.
            self._open_circuit()
        elif (
            self.circuit_state == CircuitBreakerState.CLOSED
            and self.consecutive_handler_failures >= self.circuit_breaker_threshold
        ):
            self._open_circuit()

    def _open_circuit(self) -> None:
        """Move the breaker to OPEN and (re)start the reset timer."""
        self.circuit_state = CircuitBreakerState.OPEN
        self.circuit_opened_at = time.monotonic()
        self._emit_circuit_transition("opened")

    def _close_circuit(self) -> None:
        """Move the breaker to CLOSED and clear failure state."""
        self.circuit_state = CircuitBreakerState.CLOSED
        self.circuit_opened_at = None
        self.consecutive_handler_failures = 0
        self._emit_circuit_transition("closed")

    def _transition_to_half_open(self) -> None:
        """Move the breaker to HALF_OPEN to allow a single probe read."""
        self.circuit_state = CircuitBreakerState.HALF_OPEN
        self._emit_circuit_transition("half_open")

    def _emit_circuit_transition(self, state: str) -> None:
        """Record the metric and emit the trace for a breaker transition.

        Both emissions are best-effort: the trace emitter swallows its own
        errors, and this runs after the state has already changed, so an
        instrumentation failure never alters the state machine outcome.

        Args:
            state: One of ``"opened"``, ``"closed"``, or ``"half_open"``.
        """
        metrics = get_domain_metrics(self.engine.domain)
        metrics.subscription_circuit_breaker_state.add(
            1,
            {
                "subscription": self.subscriber_class_name,
                "handler": self.subscriber_class_name,
                "state": state,
            },
        )
        self.engine.emitter.emit(
            event=f"subscription.circuit_breaker.{state}",
            stream=self.stream_category,
            message_id=self.subscription_id,
            message_type="circuit_breaker",
            status=state,
            handler=self.subscriber_class_name,
            metadata={
                "consecutive_handler_failures": self.consecutive_handler_failures,
                "circuit_breaker_threshold": self.circuit_breaker_threshold,
            },
            worker_id=self.subscription_id,
        )

    async def _read_primary_nonblocking(self) -> list[tuple[str, dict[str, Any]]]:
        """Non-blocking read from primary (production) stream.

        Uses ``timeout_ms=0`` so the call returns immediately if no messages
        are available. This ensures we never block on the primary stream when
        there might be backfill work to do.

        Returns:
            List of ``(id, payload)`` tuples from the primary stream.
        """
        if not self.broker:
            return []

        try:
            return await asyncio.to_thread(
                self.broker.read_blocking,
                stream=self.stream_category,
                consumer_group=self.consumer_group,
                consumer_name=self.consumer_name,
                timeout_ms=0,  # Non-blocking
                count=self._current_batch_size(),
            )
        except Exception as e:
            logger.error(f"Error reading primary stream {self.stream_category}: {e}")
            return []

    async def _read_backfill_blocking(self) -> list[tuple[str, dict[str, Any]]]:
        """Blocking read from backfill stream with capped timeout.

        Uses a short timeout (capped at 1 second) so we frequently re-check
        the primary stream for new production messages. If a production request
        arrives while we're blocking on backfill, we'll notice within 1 second.

        Returns:
            List of ``(id, payload)`` tuples from the backfill stream.
        """
        if not self.broker:
            return []

        try:
            # Cap at 1 second to ensure responsive primary lane re-checks
            backfill_timeout = min(self.blocking_timeout_ms, 1000)
            return await asyncio.to_thread(
                self.broker.read_blocking,
                stream=self.backfill_stream,
                consumer_group=self.consumer_group,
                consumer_name=self.consumer_name,
                timeout_ms=backfill_timeout,
                count=self._current_batch_size(),
            )
        except Exception as e:
            logger.error(f"Error reading backfill stream {self.backfill_stream}: {e}")
            return []

    async def get_next_batch_of_messages(self) -> list[tuple[str, dict[str, Any]]]:
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
                count=self._current_batch_size(),
            )

            return messages
        except Exception as e:
            logger.error(f"Error reading messages from stream: {e}")
            return []

    async def process_batch(
        self,
        messages: list[tuple[str, dict[str, Any]]],
        stream: str | None = None,
    ) -> int:
        """
        Process a batch of messages.

        This method takes a batch of messages and processes each message by calling the `handle_message` method
        of the engine. It handles retries and dead letter queue for failed messages.

        Args:
            messages (List[tuple[str, dict]]): The batch of messages to process as (id, payload) tuples.
            stream: The stream these messages came from. Used by ACK/NACK/DLQ
                operations to target the correct stream. Defaults to the primary stream.

        Returns:
            int: The number of messages processed successfully.
        """
        stream = stream or self._default_stream

        logger.debug(
            f"[{self.subscriber_class_name}] Received {len(messages)} message(s)"
        )
        successful_count = 0
        metrics = get_domain_metrics(self.engine.domain)
        attrs = {
            "subscription": self.subscriber_class_name,
            "handler": self.subscriber_class_name,
            "stream": stream,
        }

        for identifier, payload in messages:
            message = await self._deserialize_message(identifier, payload, stream)
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
            msg_start = time.monotonic()
            is_successful = await self.engine.handle_message(
                self.handler, message, worker_id=self.subscription_id
            )
            elapsed = time.monotonic() - msg_start

            metrics.subscription_processing_duration.record(elapsed, attrs)

            # Record handler outcome independent of broker ACK
            metrics.subscription_messages_processed.add(
                1, {**attrs, "status": "ok" if is_successful else "error"}
            )

            # Advance the circuit breaker on the handler outcome. This is
            # separate from the ACK/NACK/DLQ paths below, which are untouched.
            self._record_handler_outcome(is_successful)

            if is_successful:
                if await self._acknowledge_message(identifier, message, stream):
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
                await self.handle_failed_message(identifier, payload, stream)

        return successful_count

    async def _deserialize_message(
        self, identifier: str, payload: dict[str, Any], stream: str | None = None
    ) -> Message | None:
        """Deserialize a message payload, handling errors by moving to DLQ."""
        try:
            return Message.deserialize(payload)
        except Exception as e:
            logger.error(f"Deserialization failed for message {identifier}: {e}")
            await self.move_to_dlq(identifier, payload, stream)
            return None

    async def _acknowledge_message(
        self,
        identifier: str,
        message: Message | None = None,
        stream: str | None = None,
    ) -> bool:
        """Acknowledge successful message processing.

        Args:
            identifier: The message identifier to ACK.
            message: The deserialized message (used for tracing metadata).
            stream: The stream to ACK on. Defaults to the primary stream.
        """
        assert self.broker is not None, "Broker not initialized"
        stream = stream or self._default_stream
        ack_result = self.broker.ack(stream, identifier, self.consumer_group)
        if ack_result:
            # Clear retry count if exists
            self.retry_counts.pop(identifier, None)

            # Emit message.acked trace
            if message and message.metadata:
                self.engine.emitter.emit(
                    event="message.acked",
                    stream=stream,
                    message_id=message.metadata.headers.id or identifier,
                    message_type=message.metadata.headers.type or "unknown",
                    handler=self.subscriber_class_name,
                    worker_id=self.subscription_id,
                    correlation_id=(
                        message.metadata.domain.correlation_id
                        if message.metadata.domain
                        else None
                    ),
                    causation_id=(
                        message.metadata.domain.causation_id
                        if message.metadata.domain
                        else None
                    ),
                )

            return True
        else:
            logger.warning(f"Failed to acknowledge message {identifier}")
            return False

    async def handle_failed_message(
        self, identifier: str, payload: dict[str, Any], stream: str | None = None
    ) -> None:
        """
        Handle a message that failed processing.

        Implements retry logic and moves to DLQ after max retries.

        Args:
            identifier: The message identifier.
            payload: The message payload.
            stream: The stream the message came from. Defaults to the primary stream.
        """
        stream = stream or self._default_stream
        retry_count = self._increment_retry_count(identifier)

        if retry_count < self.max_retries:
            await self._retry_message(identifier, retry_count, stream)
        else:
            await self._exhaust_retries(identifier, payload, stream)

    def _increment_retry_count(self, identifier: str) -> int:
        """Increment and return the retry count for a message."""
        self.retry_counts[identifier] = self.retry_counts.get(identifier, 0) + 1
        return self.retry_counts[identifier]

    async def _retry_message(
        self, identifier: str, retry_count: int, stream: str | None = None
    ) -> None:
        """Retry a failed message after delay.

        Args:
            identifier: The message identifier to NACK.
            retry_count: Current retry attempt number.
            stream: The stream to NACK on. Defaults to the primary stream.
        """
        assert self.broker is not None, "Broker not initialized"
        stream = stream or self._default_stream

        metrics = get_domain_metrics(self.engine.domain)
        metrics.subscription_retries.add(
            1,
            {
                "subscription": self.subscriber_class_name,
                "handler": self.subscriber_class_name,
                "stream": stream,
            },
        )

        logger.debug(
            f"Retrying message {identifier} (attempt {retry_count}/{self.max_retries}) "
            f"after {self.retry_delay_seconds}s delay"
        )

        # Emit message.nacked trace
        self.engine.emitter.emit(
            event="message.nacked",
            stream=stream,
            message_id=identifier,
            message_type="unknown",
            status="retry",
            handler=self.subscriber_class_name,
            metadata={"retry_count": retry_count, "max_retries": self.max_retries},
            worker_id=self.subscription_id,
        )

        await asyncio.sleep(self.retry_delay_seconds)

        # NACK the message to make it available for reprocessing
        self.broker.nack(stream, identifier, self.consumer_group)

    async def _exhaust_retries(
        self, identifier: str, payload: dict[str, Any], stream: str | None = None
    ) -> None:
        """Handle a message that has exhausted all retries.

        Moves the message to the DLQ (if enabled) and then ACKs it, clearing the
        retry count. If the DLQ publish fails, the message is NOT ACKed and the
        retry count is retained: it is NACKed so the broker redelivers it and the
        DLQ move is retried, rather than the message being silently lost.

        Args:
            identifier: The message identifier.
            payload: The message payload.
            stream: The stream to ACK on. Defaults to the primary stream.
        """
        assert self.broker is not None, "Broker not initialized"
        stream = stream or self._default_stream
        logger.warning(
            f"Message {identifier} exhausted retries ({self.max_retries} attempts), "
            f"{'moving to DLQ' if self.enable_dlq else 'discarding'}"
        )
        if not await self.move_to_dlq(identifier, payload, stream):
            # DLQ publish failed: hold the message for redelivery instead of
            # ACKing it away. Back off first (as the retry path does) so a downed
            # DLQ is retried at the retry cadence, not hammered at poll speed (the
            # stream poll loop re-reads pending messages with no inter-poll delay).
            # Keep the retry count so the redelivery stays on the exhaust path and
            # re-attempts the DLQ move.
            await asyncio.sleep(self.retry_delay_seconds)
            nack_result = self.broker.nack(stream, identifier, self.consumer_group)
            if not nack_result:
                logger.warning(
                    f"Failed to NACK message {identifier} after a failed DLQ publish"
                )
            return

        # DLQ move succeeded (or the DLQ is disabled): ACK to remove the message
        # from the pending list and clear the retry count.
        self.broker.ack(stream, identifier, self.consumer_group)
        self.retry_counts.pop(identifier, None)

    async def move_to_dlq(
        self, identifier: str, payload: dict[str, Any], stream: str | None = None
    ) -> bool:
        """
        Move a failed message to the dead letter queue.

        Routes to the appropriate DLQ based on the source stream:
        primary messages go to ``stream:dlq``, backfill messages go to
        ``stream:backfill:dlq``.

        Args:
            identifier: The original message identifier.
            payload: The message payload.
            stream: The source stream. Defaults to the primary stream.

        Returns:
            bool: True if the message was published to the DLQ (or the DLQ is
            disabled, so there is nothing to hold); False if the publish failed,
            so the caller can hold the message for redelivery rather than ACKing
            it away.
        """
        if not self.enable_dlq:
            return True

        assert self.broker is not None, "Broker not initialized"
        stream = stream or self._default_stream

        # Use the correct DLQ stream based on source stream
        if stream == self.backfill_stream:
            dlq_target = self.backfill_dlq_stream
        else:
            dlq_target = self.dlq_stream

        try:
            dlq_message = self._create_dlq_message(identifier, payload, stream)
            self.broker.publish(dlq_target, dlq_message)
            logger.info(f"Moved message {identifier} to DLQ stream {dlq_target}")

            metrics = get_domain_metrics(self.engine.domain)
            metrics.subscription_dlq_routed.add(
                1,
                {
                    "subscription": self.subscriber_class_name,
                    "handler": self.subscriber_class_name,
                    "stream": stream,
                },
            )

            # Emit message.dlq trace
            msg_metadata = payload.get("metadata") or {}
            message_type = msg_metadata.get("headers", {}).get("type", "unknown")
            domain_meta = msg_metadata.get("domain") or {}
            self.engine.emitter.emit(
                event="message.dlq",
                stream=stream,
                message_id=identifier,
                message_type=message_type,
                status="error",
                handler=self.subscriber_class_name,
                metadata={
                    "dlq_stream": dlq_target,
                    "retry_count": self.retry_counts.get(identifier, self.max_retries),
                },
                worker_id=self.subscription_id,
                correlation_id=domain_meta.get("correlation_id"),
                causation_id=domain_meta.get("causation_id"),
            )
            return True
        except Exception as e:
            logger.exception(f"Failed to move message {identifier} to DLQ: {e}")
            return False

    def _create_dlq_message(
        self, identifier: str, payload: dict[str, Any], stream: str | None = None
    ) -> dict[str, Any]:
        """Create a DLQ message with failure metadata."""
        stream = stream or self._default_stream
        return {
            **payload,
            "_dlq_metadata": {
                "original_stream": stream,
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
