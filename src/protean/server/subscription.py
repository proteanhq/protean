import asyncio
import logging
import traceback
from typing import List, Union

from protean.core.command_handler import BaseCommandHandler
from protean.core.event_handler import BaseEventHandler
from protean.port.event_store import BaseEventStore
from protean.utils.mixins import Message, MessageType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s,%(msecs)d %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


class Subscription:
    """
    Represents a subscription to a stream in the Protean event-driven architecture.

    A subscription allows a subscriber to receive and process messages from a specific stream.
    It provides methods to start and stop the subscription, as well as process messages in batches.
    """

    def __init__(
        self,
        engine,
        subscriber_id: str,
        stream_category: str,
        handler: Union[BaseEventHandler, BaseCommandHandler],
        messages_per_tick: int = 10,
        position_update_interval: int = 10,
        origin_stream: str | None = None,
        tick_interval: int = 1,
    ) -> None:
        """
        Initialize the Subscription object.

        Args:
            engine: The Protean engine instance.
            subscriber_id (str): The unique identifier for the subscriber.
            stream_category (str): The name of the stream to subscribe to.
            handler (Union[BaseEventHandler, BaseCommandHandler]): The event or command handler.
            messages_per_tick (int, optional): The number of messages to process per tick. Defaults to 10.
            position_update_interval (int, optional): The interval at which to update the current position. Defaults to 10.
            origin_stream (str | None, optional): The name of the origin stream to filter messages. Defaults to None.
            tick_interval (int, optional): The interval between ticks. Defaults to 1.
        """
        self.engine = engine

        self.store: BaseEventStore = engine.domain.event_store.store
        self.loop = engine.loop

        self.subscriber_id = subscriber_id
        self.stream_category = stream_category
        self.handler = handler
        self.messages_per_tick = messages_per_tick
        self.position_update_interval = position_update_interval
        self.origin_stream = origin_stream
        self.tick_interval = tick_interval

        self.subscriber_stream_name = f"position-${subscriber_id}"

        self.current_position: int = -1
        self.messages_since_last_position_write: int = 0

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

        # Load own position from Event store
        await self.load_position_on_start()

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
        await self.update_current_position_to_store()
        logger.debug(f"Shutting down subscription {self.subscriber_id}")

    async def fetch_last_position(self):
        """
        Fetch the last read position from the store.

        Returns:
            int: The last read position from the store.
        """
        message = self.store._read_last_message(self.subscriber_stream_name)
        if message:
            return message["data"]["position"]

        return -1

    async def load_position_on_start(self) -> None:
        """
        Load the last position from the store when starting.

        This method retrieves the last read position from the event store and updates the current position
        of the subscription. If there is no previous position, it logs a message indicating that the
        subscription will start at the beginning of the stream.

        Returns:
            None
        """
        last_position = await self.fetch_last_position()
        if last_position > -1:
            self.current_position = last_position
            logger.debug(f"Loaded position {self.current_position} from last message")
        else:
            logger.debug(
                "No previous messages - Starting at the beginning of the stream"
            )

    async def update_current_position_to_store(self) -> int:
        """Update the current position to the store, only if out of sync.

        This method updates the current position of the subscription to the event store, but only if the
        current position is greater than the last written position.

        Returns:
            int: The last written position.
        """
        last_written_position = await self.fetch_last_position()
        if last_written_position < self.current_position:
            self.write_position(self.current_position)

        return last_written_position

    async def update_read_position(self, position) -> int:
        """
        Update the current read position.

        If at or beyond the configured interval, write position to the store.

        Args:
            position (int): The new read position.

        Returns:
            int: The updated read position.
        """
        self.current_position = position
        self.messages_since_last_position_write += 1

        if self.messages_since_last_position_write >= self.position_update_interval:
            self.write_position(position)

        return self.current_position

    def write_position(self, position: int) -> int:
        """
        Write the position to the store.

        This method writes the current read position to the event store. It updates the read position
        of the subscriber and resets the counter for messages since the last position write.

        Args:
            position (int): The read position to be written.

        Returns:
            int: The position that was written.
        """
        logger.debug(f"Updating Read Position of {self.subscriber_id} to {position}")

        self.messages_since_last_position_write = 0  # Reset counter

        return self.store._write(
            self.subscriber_stream_name,
            "Read",
            {"position": position},
            metadata={
                "kind": MessageType.READ_POSITION.value,
                "origin_stream": self.stream_category,
            },
        )

    def filter_on_origin(self, messages: List[Message]) -> List[Message]:
        """
        Filter messages based on the origin stream name.

        Args:
            messages (List[Message]): The list of messages to filter.

        Returns:
            List[Message]: The filtered list of messages.
        """
        if not self.origin_stream:
            return messages

        filtered_messages = []

        for message in messages:
            origin_stream = message.metadata and self.store.category(
                message.metadata.origin_stream
            )

            if self.origin_stream == origin_stream:
                filtered_messages.append(message)

        logger.debug(f"Filtered {len(filtered_messages)} out of {len(messages)}")
        return filtered_messages

    async def get_next_batch_of_messages(self):
        """
        Get the next batch of messages to process.

        This method reads messages from the event store starting from the current position + 1.
        It retrieves a specified number of messages per tick and applies filtering based on the origin stream name.

        Returns:
            List[Message]: The next batch of messages to process.
        """
        messages = self.store.read(
            self.stream_category,
            position=self.current_position + 1,
            no_of_messages=self.messages_per_tick,
        )  # FIXME Implement filtering

        return self.filter_on_origin(messages)

    async def process_batch(self, messages):
        """
        Process a batch of messages.

        This method takes a batch of messages and processes each message by calling the `handle_message` method
        of the engine. It also updates the read position after processing each message. If an exception occurs
        during message processing, it logs the error.

        Args:
            messages (List[Message]): The batch of messages to process.

        Returns:
            int: The number of messages processed successfully.
        """
        logging.debug(f"Processing {len(messages)} messages...")
        successful_count = 0

        for message in messages:
            logging.info(f"{message.type}-{message.id} : {message.to_dict()}")
            # Process the message and get a success/failure result
            is_successful = await self.engine.handle_message(self.handler, message)

            # Always update position to avoid reprocessing the message
            await self.update_read_position(message.global_position)

            # Increment counter only for successful messages
            if is_successful:
                successful_count += 1

        return successful_count
