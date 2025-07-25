import logging
import os
import secrets
import socket
from typing import Type

from protean.core.subscriber import BaseSubscriber
from protean.port.broker import BaseBroker
from protean.utils import fqn

from . import BaseSubscription

logger = logging.getLogger(__name__)


class BrokerSubscription(BaseSubscription):
    """
    Represents a subscription to a broker stream.

    A broker subscription allows a subscriber to receive and process messages from a specific stream
    using a broker backend. It provides consumer group management and message acknowledgment capabilities.
    """

    def __init__(
        self,
        engine,
        broker,
        stream_name: str,
        handler: Type[BaseSubscriber],
        messages_per_tick: int = 10,
        tick_interval: int = 1,
    ) -> None:
        """
        Initialize the BrokerSubscription object.

        Args:
            engine: The Protean engine instance.
            broker: The broker instance.
            subscriber_name (str): FQN of the subscriber.
            stream_name (str): The name of the stream to subscribe to.
            handler (Type[BaseSubscriber]): The subscriber handler.
            messages_per_tick (int, optional): The number of messages to process per tick. Defaults to 10.
            tick_interval (int, optional): The interval between ticks. Defaults to 1.
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

        # Ensure consumer group exists for this stream
        self.broker._ensure_group(self.subscriber_name, self.stream_name)

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

        This method takes a batch of messages and processes each message by calling the `handle_broker_message` method
        of the engine. It handles acknowledgment/negative acknowledgment based on processing result.

        Args:
            messages (List[dict]): The batch of messages to process.

        Returns:
            int: The number of messages processed successfully.
        """
        logging.debug(f"Processing {len(messages)} messages...")
        successful_count = 0

        for message in messages:
            identifier, payload = message
            # Process the message and get a success/failure result
            is_successful = await self.engine.handle_broker_message(
                self.handler, payload
            )

            # Handle ack/nack based on processing result
            if is_successful:
                # Acknowledge successful processing
                ack_result = self.broker.ack(
                    self.stream_name, identifier, self.subscriber_name
                )
                if ack_result:
                    successful_count += 1
                else:
                    logging.warning(f"Failed to acknowledge message {identifier}")
            else:
                # Negative acknowledge for failed processing
                nack_result = self.broker.nack(
                    self.stream_name, identifier, self.subscriber_name
                )
                if not nack_result:
                    logging.warning(f"Failed to nack message {identifier}")

        return successful_count
