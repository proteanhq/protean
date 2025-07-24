import logging
from typing import List, Optional

from protean.port.broker import BaseBroker
from protean.utils.outbox import Outbox, OutboxRepository, ProcessingResult

from .subscription import BaseSubscription

logger = logging.getLogger(__name__)


class OutboxProcessor(BaseSubscription):
    """
    Processes outbox messages by publishing them to a broker.

    OutboxProcessor polls the outbox table for unprocessed messages and publishes
    them to the configured broker. It handles message lifecycle status updates
    and provides retry mechanisms for failed messages.
    """

    def __init__(
        self,
        engine,
        database_provider_name: str,
        broker_provider_name: str,
        messages_per_tick: int = 10,
        tick_interval: int = 1,
        worker_id: Optional[str] = None,
    ) -> None:
        """
        Initialize the OutboxProcessor.

        Args:
            engine: The Protean engine instance.
            database_provider_name (str): Name of the database provider to read outbox messages from.
            broker_provider_name (str): Name of the broker provider to publish messages to.
            messages_per_tick (int, optional): The number of messages to process per tick. Defaults to 10.
            tick_interval (int, optional): The interval between ticks. Defaults to 1.
            worker_id (str, optional): Worker identifier for message locking. Defaults to subscription_id.
        """
        # Initialize parent class - use dummy handler to satisfy BaseSubscription requirements
        super().__init__(engine, messages_per_tick, tick_interval)

        self.subscription_id = (
            f"outbox-processor-{database_provider_name}-to-{broker_provider_name}"
        )

        self.database_provider_name = database_provider_name
        self.broker_provider_name = broker_provider_name
        self.worker_id = worker_id or self.subscription_id

        # Will be initialized in initialize() method
        self.subscriber_name: Optional[str] = None
        self.broker: Optional[BaseBroker] = None
        self.outbox_repo: Optional[OutboxRepository] = None

    async def initialize(self) -> None:
        """
        Perform initialization specific to outbox processing.

        This method initializes the broker connection and outbox repository.
        """
        # Get the broker for this provider
        if self.broker_provider_name not in self.engine.domain.brokers:
            raise ValueError(
                f"Broker provider '{self.broker_provider_name}' not configured in domain"
            )

        self.broker = self.engine.domain.brokers[self.broker_provider_name]

        # Get the outbox repository for this database provider
        self.outbox_repo = self.engine.domain._get_outbox_repo(
            self.database_provider_name
        )

        if not self.outbox_repo:
            raise ValueError(
                f"Outbox repository for database provider '{self.database_provider_name}' not found in domain"
            )

        # Set the subscriber to the custom Outbox aggregate name
        self.subscriber_name = self.outbox_repo.meta_.part_of.__name__

        logger.debug(
            f"Initialized OutboxProcessor for database '{self.database_provider_name}' to broker '{self.broker_provider_name}'"
        )

    async def get_next_batch_of_messages(self) -> List[Outbox]:
        """
        Get the next batch of unprocessed outbox messages.

        Returns:
            List[Outbox]: The next batch of outbox messages ready for processing.
        """
        if not self.outbox_repo:
            return []

        messages = self.outbox_repo.find_unprocessed(limit=self.messages_per_tick)
        logger.debug(f"Found {len(messages)} unprocessed outbox messages")

        return messages

    async def process_batch(self, messages: List[Outbox]) -> int:
        """
        Process a batch of outbox messages.

        This method processes each message by:
        1. Acquiring a processing lock
        2. Publishing the message to the broker
        3. Updating the message status based on success/failure

        Note that each persistence operation is instantly committed to db, because
        there is no UoW in this context.

        Args:
            messages (List[Outbox]): The batch of outbox messages to process.

        Returns:
            int: The number of messages processed successfully.
        """
        logger.debug(f"Processing {len(messages)} outbox messages...")
        successful_count = 0

        for message in messages:
            try:
                # Attempt to acquire lock and start processing
                success, result = message.start_processing(self.worker_id)
                if not success:
                    # Log the specific reason why message was skipped at INFO level for production visibility
                    reason_messages = {
                        ProcessingResult.NOT_ELIGIBLE: f"Message {message.message_id} not eligible (status: {message.status})",
                        ProcessingResult.ALREADY_LOCKED: f"Message {message.message_id} already locked by {message.locked_by} until {message.locked_until}",
                        ProcessingResult.MAX_RETRIES_EXCEEDED: f"Message {message.message_id} exceeded max retries ({message.retry_count}/{message.max_retries})",
                        ProcessingResult.RETRY_NOT_DUE: f"Message {message.message_id} retry not due until {message.next_retry_at}",
                    }
                    logger.info(
                        reason_messages.get(
                            result,
                            f"Message {message.message_id} skipped for unknown reason: {result}",
                        )
                    )
                    continue

                # Publish message to broker
                success = await self._publish_message(message)

                if success:
                    # Mark as published and save
                    message.mark_published()
                    self.outbox_repo.add(message)

                    successful_count += 1
                    logger.info(
                        f"Successfully published outbox message {message.message_id} to {message.stream_name}"
                    )
                else:
                    # Mark as failed and save
                    error = Exception("Failed to publish message to broker")
                    message.mark_failed(error)

                    self.outbox_repo.add(message)
                    logger.error(
                        f"Failed to publish outbox message {message.message_id}: {error}"
                    )
            except Exception as exc:
                logger.error(
                    f"Error processing outbox message {message.message_id}: {str(exc)}"
                )
                try:
                    # Mark as failed and save
                    message.mark_failed(exc)
                    self.outbox_repo.add(message)
                except Exception as save_exc:
                    logger.error(
                        f"Failed to save failed message status for {message.message_id}: {save_exc}"
                    )

        return successful_count

    async def _publish_message(self, message: Outbox) -> bool:
        """
        Publish a single outbox message to the broker.

        Args:
            message (Outbox): The outbox message to publish.

        Returns:
            bool: True if message was published successfully, False otherwise.
        """
        try:
            # Prepare the message payload for the broker
            message_payload = {
                "id": message.message_id,
                "type": message.type,
                "data": message.data,
                "metadata": message.metadata.to_dict() if message.metadata else {},
                "created_at": message.created_at.isoformat()
                if message.created_at
                else None,
            }

            # Add correlation and trace IDs if available
            if message.correlation_id:
                message_payload["correlation_id"] = message.correlation_id
            if message.trace_id:
                message_payload["trace_id"] = message.trace_id

            # Publish to broker
            broker_message_id = self.broker.publish(
                message.stream_name, message_payload
            )

            logger.debug(
                f"Published message {message.message_id} to broker as {broker_message_id}"
            )
            return True

        except Exception as exc:
            logger.error(
                f"Broker publish failed for message {message.message_id}: {str(exc)}"
            )
            return False

    async def cleanup(self) -> None:
        """
        Perform cleanup tasks during shutdown.

        This method handles any necessary cleanup when the processor is shutting down.
        """
        logger.debug(
            f"Cleaning up OutboxProcessor for database '{self.database_provider_name}' to broker '{self.broker_provider_name}'"
        )
        # Any cleanup specific to outbox processor can be added here
        pass
