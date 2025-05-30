import asyncio
import logging
from typing import Type

from protean.core.subscriber import BaseSubscriber
from protean.port.broker import BaseBroker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


class BrokerSubscription:
    """
    Represents a subscription to a broker channel.

    A broker subscription allows a subscriber to receive and process messages from a specific channel.
    It provides methods to start and stop the subscription, as well as process messages in batches.
    """

    def __init__(
        self,
        engine,
        broker,
        subscriber_id: str,
        channel: str,
        handler: Type[BaseSubscriber],
        messages_per_tick: int = 10,
        tick_interval: int = 1,
    ) -> None:
        """
        Initialize the Subscription object.

        Args:
            engine: The Protean engine instance.
            subscriber_id (str): The unique identifier for the subscriber.
            channel (str): The name of the stream to subscribe to.
            handler (Union[BaseEventHandler, BaseCommandHandler]): The event or command handler.
            messages_per_tick (int, optional): The number of messages to process per tick. Defaults to 10.
            tick_interval (int, optional): The interval between ticks. Defaults to 1.
        """
        self.engine = engine
        self.broker: BaseBroker = broker
        self.loop = engine.loop

        self.subscriber_id = subscriber_id
        self.channel = channel
        self.handler = handler
        self.messages_per_tick = messages_per_tick
        self.tick_interval = tick_interval

        self.keep_going = True  # Initially set to keep going

    async def start(self) -> None:
        """
        Start the subscription.

        This method initializes the subscription by loading the last position from the event store
        and starting the polling loop.

        Returns:
            None
        """
        logger.debug(f"Starting {self.subscriber_id}")

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
        await self.tick()

        if self.keep_going and not self.engine.shutting_down:
            # Keep control of the loop if in test mode
            #   Otherwise `asyncio.sleep` will give away control and
            #   the loop will be able to be stopped with `shutdown()`
            if not self.engine.test_mode:
                await asyncio.sleep(self.tick_interval)

            self.loop.create_task(self.poll())

    async def tick(self):
        """
        This method retrieves the next batch of messages to process and calls the `process_batch` method
        to handle each message. It also updates the read position after processing each message.

        Returns:
            None
        """
        messages = await self.get_next_batch_of_messages()
        if messages:
            await self.process_batch(messages)

    async def shutdown(self):
        """
        Shutdown the subscription.

        This method signals the subscription to stop polling and updates the current position to the store.
        It also logs a message indicating the shutdown of the subscription.

        Returns:
            None
        """
        self.keep_going = False  # Signal to stop polling
        logger.debug(f"Shutting down subscription {self.subscriber_id}")

    async def get_next_batch_of_messages(self):
        """
        Get the next batch of messages to process.

        This method reads messages from the event store starting from the current position + 1.
        It retrieves a specified number of messages per tick and applies filtering based on the origin stream name.

        Returns:
            List[Message]: The next batch of messages to process.
        """
        messages = self.broker.read(
            self.channel,
            no_of_messages=self.messages_per_tick,
        )  # FIXME Implement filtering

        return messages

    async def process_batch(self, messages: list[dict]):
        """
        Process a batch of messages.

        This method takes a batch of messages and processes each message by calling the `handle_broker_message` method
        of the engine. If an exception occurs during message processing, it logs the error.

        Args:
            messages (List[dict]): The batch of messages to process.

        Returns:
            int: The number of messages processed successfully.
        """
        logging.debug(f"Processing {len(messages)} messages...")
        successful_count = 0

        for message in messages:
            # Process the message and get a success/failure result
            is_successful = await self.engine.handle_broker_message(
                self.handler, message
            )

            # Increment counter only for successful messages
            if is_successful:
                successful_count += 1

        return successful_count
