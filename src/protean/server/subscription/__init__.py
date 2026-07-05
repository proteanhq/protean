import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from protean.server.engine import Engine

logger = logging.getLogger(__name__)


class BaseSubscription(ABC):
    """
    Base class for all subscription types in the Protean event-driven architecture.

    A subscription allows a subscriber to receive and process messages from a specific stream.
    It provides methods to start and stop the subscription, as well as process messages in batches.
    """

    # Human-readable identifier for the subscriber, set by each concrete
    # subscription in its ``__init__`` (typically ``fqn(self.handler)``). The
    # base class reads it for structured logging.
    subscriber_name: str

    def __init__(
        self,
        engine: "Engine",
        messages_per_tick: int = 10,
        tick_interval: float = 1,
    ) -> None:
        """
        Initialize the BaseSubscription object.

        Args:
            engine: The Protean engine instance.
            handler: The handler instance.
            messages_per_tick (int, optional): The number of messages to process per tick. Defaults to 10.
            tick_interval (float, optional): The interval between ticks (seconds). Defaults to 1.
        """
        self.engine = engine
        self.loop = engine.loop

        self.messages_per_tick = messages_per_tick
        self.tick_interval = tick_interval

        self.keep_going = True  # Initially set to keep going

    async def start(self) -> None:
        """
        Start the subscription.

        This method initializes the subscription and starts the polling loop.

        Returns:
            None
        """
        logger.info(
            "subscription.started",
            extra={"subscriber": self.subscriber_name},
        )

        # Perform backend-specific initialization
        await self.initialize()

        # Start the polling loop
        self.loop.create_task(self.poll())

    async def poll(self) -> None:
        """
        Polling loop for processing messages.

        This method continuously polls for new messages and processes them by calling the `tick` method.
        It uses cooperative multitasking to ensure smooth interleaving with other tasks.

        Returns:
            None
        """
        consecutive_errors = 0

        while self.keep_going and not self.engine.shutting_down:
            try:
                with self.engine.domain.domain_context():
                    # Process messages
                    await self.tick()

                    # Reset error counter on successful tick
                    consecutive_errors = 0

                    # Use minimal sleep for cooperative multitasking
                    # This ensures interleaving without blocking
                    if self.tick_interval > 0:
                        await asyncio.sleep(self.tick_interval)
                    else:
                        # Always yield control to allow other tasks to run
                        await asyncio.sleep(0)

            except asyncio.CancelledError:
                logger.info(
                    "subscription.cancelled",
                    extra={"subscriber": self.subscriber_name},
                )
                break

            except Exception:
                consecutive_errors += 1
                logger.exception(
                    "subscription.error",
                    extra={
                        "subscriber": self.subscriber_name,
                        "attempt": consecutive_errors,
                    },
                )
                # Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
                backoff = min(2 ** (consecutive_errors - 1), 30)
                await asyncio.sleep(backoff)

    async def tick(self) -> None:
        """
        This method retrieves the next batch of messages to process and calls the `process_batch` method
        to handle each message.

        Returns:
            None
        """
        messages = await self.get_next_batch_of_messages()
        if messages:
            await self.process_batch(messages)

    async def shutdown(self) -> None:
        """
        Shutdown the subscription.

        This method signals the subscription to stop polling and performs any necessary cleanup.

        Returns:
            None
        """
        self.keep_going = False  # Signal to stop polling
        await self.cleanup()
        logger.info(
            "subscription.shutdown",
            extra={"subscriber": self.subscriber_name},
        )

    async def initialize(self) -> None:
        """
        Perform backend-specific initialization.

        This method should be implemented by subclasses to handle any initialization
        specific to their backend (event store, broker, etc.).

        Returns:
            None
        """
        pass

    @abstractmethod
    async def get_next_batch_of_messages(self) -> list[Any]:
        """
        Get the next batch of messages to process.

        This method should be implemented by subclasses to retrieve messages
        from their specific backend. The element type of the returned list is
        backend-specific (domain ``Message``, broker ``(id, payload)`` tuples,
        ``Outbox`` rows, ...), hence the ``list[Any]`` contract at the port.

        Returns:
            The next batch of messages to process.
        """

    @abstractmethod
    async def process_batch(self, messages: Any) -> int:
        """
        Process a batch of messages.

        This method should be implemented by subclasses to handle the processing
        of messages specific to their backend. ``messages`` is backend-specific
        (see :meth:`get_next_batch_of_messages`), hence typed ``Any`` at the port.

        Args:
            messages: The batch of messages to process.

        Returns:
            int: The number of messages processed successfully.
        """

    async def cleanup(self) -> None:
        """
        Perform any cleanup tasks during shutdown.

        This method should be implemented by subclasses to handle any cleanup
        specific to their backend.

        Returns:
            None
        """
        pass
