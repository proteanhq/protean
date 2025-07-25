import asyncio
import logging
from abc import ABC, abstractmethod

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


class BaseSubscription(ABC):
    """
    Base class for all subscription types in the Protean event-driven architecture.

    A subscription allows a subscriber to receive and process messages from a specific stream.
    It provides methods to start and stop the subscription, as well as process messages in batches.
    """

    def __init__(
        self,
        engine,
        messages_per_tick: int = 10,
        tick_interval: int = 1,
    ) -> None:
        """
        Initialize the BaseSubscription object.

        Args:
            engine: The Protean engine instance.
            handler: The handler instance.
            messages_per_tick (int, optional): The number of messages to process per tick. Defaults to 10.
            tick_interval (int, optional): The interval between ticks. Defaults to 1.
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
        logger.debug(f"Starting {self.subscriber_name}")

        # Perform backend-specific initialization
        await self.initialize()

        # Start the polling loop
        self.loop.create_task(self.poll())

    async def poll(self) -> None:
        """
        Polling loop for processing messages.

        This method continuously polls for new messages and processes them by calling the `tick` method.
        It sleeps for the specified `tick_interval` between each tick.

        Returns:
            None
        """
        while self.keep_going and not self.engine.shutting_down:
            await self.tick()

            # Keep control of the loop if in test mode
            #   Otherwise `asyncio.sleep` will give away control and
            #   the loop will be able to be stopped with `shutdown()`
            if not self.engine.test_mode:
                await asyncio.sleep(self.tick_interval)
            else:
                # In test mode, yield control briefly to allow shutdown
                await asyncio.sleep(0)

    async def tick(self):
        """
        This method retrieves the next batch of messages to process and calls the `process_batch` method
        to handle each message.

        Returns:
            None
        """
        messages = await self.get_next_batch_of_messages()
        if messages:
            await self.process_batch(messages)

    async def shutdown(self):
        """
        Shutdown the subscription.

        This method signals the subscription to stop polling and performs any necessary cleanup.

        Returns:
            None
        """
        self.keep_going = False  # Signal to stop polling
        await self.cleanup()
        logger.debug(f"Shutting down subscription {self.subscriber_name}")

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
    async def get_next_batch_of_messages(self):
        """
        Get the next batch of messages to process.

        This method should be implemented by subclasses to retrieve messages
        from their specific backend.

        Returns:
            The next batch of messages to process.
        """

    @abstractmethod
    async def process_batch(self, messages):
        """
        Process a batch of messages.

        This method should be implemented by subclasses to handle the processing
        of messages specific to their backend.

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
