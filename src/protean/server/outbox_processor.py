import asyncio
import logging
from typing import List, Optional

from protean.core.unit_of_work import UnitOfWork
from protean.port.broker import BaseBroker
from protean.utils.eventing import Message
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

        # Load retry configuration from domain config
        retry_config = engine.domain.config.get("outbox", {}).get("retry", {})
        self.retry_config = {
            "max_attempts": retry_config.get("max_attempts", 3),
            "base_delay_seconds": retry_config.get("base_delay_seconds", 60),
            "max_backoff_seconds": retry_config.get("max_backoff_seconds", 3600),
            "backoff_multiplier": retry_config.get("backoff_multiplier", 2),
            "jitter": retry_config.get("jitter", True),
            "jitter_factor": retry_config.get("jitter_factor", 0.25),
        }

        # Load cleanup configuration from domain config
        cleanup_config = engine.domain.config.get("outbox", {}).get("cleanup", {})
        self.cleanup_config = {
            "published_retention_hours": cleanup_config.get(
                "published_retention_hours", 168
            ),  # 7 days
            "abandoned_retention_hours": cleanup_config.get(
                "abandoned_retention_hours", 720
            ),  # 30 days
            "cleanup_interval_ticks": cleanup_config.get(
                "cleanup_interval_ticks", 86400
            ),
        }

        self.tick_count = 0

        # Will be initialized in initialize() method
        self.subscriber_name: Optional[str] = None
        self.broker: Optional[BaseBroker] = None
        self.outbox_repo: Optional[OutboxRepository] = None

    async def initialize(self) -> None:
        """
        Perform initialization specific to outbox processing.

        This method initializes the broker connection and outbox repository.
        """
        logger.debug(
            f"Initializing outbox processor: {self.database_provider_name} -> {self.broker_provider_name}"
        )

        # Get the broker for this provider
        if self.broker_provider_name not in self.engine.domain.brokers:
            raise ValueError(
                f"Broker provider '{self.broker_provider_name}' not configured in domain"
            )

        self.broker = self.engine.domain.brokers[self.broker_provider_name]
        logger.debug(f"Using broker: {self.broker.__class__.__name__}")

        # Get the outbox repository for this database provider
        self.outbox_repo = self.engine.domain._get_outbox_repo(
            self.database_provider_name
        )

        if not self.outbox_repo:
            raise ValueError(
                f"Outbox repository for database provider '{self.database_provider_name}' not found in domain"
            )

        logger.debug(f"Using outbox repository: {self.outbox_repo.__class__.__name__}")

        # Set the subscriber to the custom Outbox aggregate name
        self.subscriber_name = self.outbox_repo.meta_.part_of.__name__

        logger.debug(
            f"Outbox processor initialized: {self.database_provider_name} -> {self.broker_provider_name}"
        )

    async def get_next_batch_of_messages(self) -> List[Outbox]:
        """
        Get the next batch of unprocessed outbox messages.

        Returns:
            List[Outbox]: The next batch of outbox messages ready for processing.
        """
        if not self.outbox_repo:
            logger.warning("Outbox repository not available")
            return []

        # Run the database query in a thread pool to avoid blocking the event loop
        # This allows other async tasks to run concurrently
        messages = await asyncio.to_thread(
            self.outbox_repo.find_unprocessed, limit=self.messages_per_tick
        )
        if messages:
            logger.debug(f"Found {len(messages)} messages to process")
        else:
            pass  # No logging needed for empty batches

        return messages

    async def process_batch(self, messages: List[Outbox]) -> int:
        """
        Process a batch of outbox messages.

        Each message is processed individually within its own atomic transaction
        to ensure consistency and avoid race conditions in multi-processor environments.

        Args:
            messages (List[Outbox]): The batch of outbox messages to process.

        Returns:
            int: The number of messages processed successfully.
        """
        successful_count = 0

        for message in messages:
            success = await self._process_single_message(message)
            if success:
                successful_count += 1
            # Yield control after each message for better interleaving
            await asyncio.sleep(0)

        if len(messages) > 0:
            logger.debug(f"Outbox batch: {successful_count}/{len(messages)} processed")
        return successful_count

    async def tick(self):
        """
        Override base tick method to add periodic cleanup functionality.

        This method processes messages and periodically performs cleanup of old messages.
        """
        # Call parent tick method to process messages
        await super().tick()

        # Increment tick counter and check if cleanup is due
        self.tick_count += 1
        # Adjust cleanup interval for continuous processing
        # (cleanup_interval_ticks is too high for fast ticking)
        cleanup_check_interval = min(
            self.cleanup_config["cleanup_interval_ticks"], 10000
        )
        if self.tick_count >= cleanup_check_interval:
            await self._perform_cleanup()
            self.tick_count = 0  # Reset counter

    async def _perform_cleanup(self) -> None:
        """
        Perform cleanup of old outbox messages using configured retention periods.
        """
        if not self.outbox_repo:
            return

        try:
            with UnitOfWork():
                cleanup_result = self.outbox_repo.cleanup_old_messages(
                    published_retention_hours=self.cleanup_config[
                        "published_retention_hours"
                    ],
                    abandoned_retention_hours=self.cleanup_config[
                        "abandoned_retention_hours"
                    ],
                )

                if cleanup_result["total"] > 0:
                    logger.info(
                        f"Outbox cleanup: removed {cleanup_result['total']} messages "
                        f"({cleanup_result['published']} published, {cleanup_result['abandoned']} abandoned)"
                    )

        except Exception as exc:
            logger.exception(f"Outbox cleanup failed: {exc}")

    async def _process_single_message(self, message: Outbox) -> bool:
        """
        Process a single outbox message atomically.

        This method handles the complete lifecycle of a message within a single
        transaction to ensure atomicity and consistency across multiple processors.

        Args:
            message (Outbox): The outbox message to process.

        Returns:
            bool: True if message was processed successfully, False otherwise.
        """
        # Start processing single message
        try:
            # Use UnitOfWork for atomic transaction management
            # This ensures all operations (lock, publish, status update) are atomic
            with UnitOfWork():
                # Attempt to acquire lock and start processing
                success, result = message.start_processing(self.worker_id)
                if not success:
                    # Log the specific reason why message was skipped
                    if result != ProcessingResult.NOT_ELIGIBLE:
                        reason_messages = {
                            ProcessingResult.ALREADY_LOCKED: f"Message {message.message_id} already locked",
                            ProcessingResult.MAX_RETRIES_EXCEEDED: f"Message {message.message_id} exceeded max retries",
                            ProcessingResult.RETRY_NOT_DUE: f"Message {message.message_id} retry not due yet",
                        }
                        logger.debug(
                            reason_messages.get(
                                result,
                                f"Message {message.message_id[:8]}... skipped: {result}",
                            )
                        )
                    return False

                # Save the lock acquisition (PROCESSING status)
                self.outbox_repo.add(message)

                # Publish message to broker
                publish_success, publish_error = await self._publish_message(message)

                # Update final status based on broker publish result
                if publish_success:
                    message.mark_published()
                    logger.debug(
                        f"Published to {message.stream_name}: {message.message_id[:8]}..."
                    )
                else:
                    self._mark_message_failed(message, publish_error)
                    logger.warning(
                        f"Publish failed for {message.message_id[:8]}...: {publish_error}"
                    )

                # Save the final status
                self.outbox_repo.add(message)

                # UnitOfWork commits here - either all operations succeed or all rollback
                return publish_success

        except Exception as exc:
            logger.exception(
                f"Error processing message {message.message_id[:8]}...: {exc}"
            )
            # Transaction automatically rolls back on exception

            # Try to save the error state in a separate transaction
            try:
                with UnitOfWork():
                    # Reload message to get fresh state (in case transaction rolled back)
                    fresh_message = self.outbox_repo.get(message.id)
                    if fresh_message:
                        self._mark_message_failed(fresh_message, exc)
                        self.outbox_repo.add(fresh_message)
            except Exception as save_exc:
                logger.error(
                    f"Failed to save failed message status for {message.message_id}: {save_exc}"
                )

            return False

    async def _publish_message(self, message: Outbox) -> tuple[bool, Exception | None]:
        """
        Publish a single outbox message to the broker.

        Reconstructs a Message object from the outbox record and publishes
        it with the standard structure (data and metadata).

        Args:
            message (Outbox): The outbox message to publish.

        Returns:
            tuple[bool, Exception | None]: (success, error) - True and None if successful, False and exception if failed.
        """
        try:
            # Reconstruct the Message object from outbox record
            # The outbox already contains the proper data and metadata fields
            msg = Message(
                data=message.data,
                metadata=message.metadata,
            )

            # Convert to dict for publishing - this gives us the standard structure
            # with top-level 'data' and 'metadata' keys
            message_dict = msg.to_dict()

            # Publish the standardized message structure to broker
            broker_message_id = self.broker.publish(
                message.metadata.domain.stream_category, message_dict
            )

            logger.debug(
                f"Published message {message.message_id} to broker as {broker_message_id}"
            )
            return True, None

        except Exception as exc:
            logger.error(
                f"Broker publish failed for message {message.message_id}: {str(exc)}"
            )
            return False, exc

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

    def _mark_message_failed(self, message: Outbox, error: Exception) -> None:
        """
        Mark message as failed using configured retry parameters.

        Args:
            message (Outbox): The message to mark as failed.
            error (Exception): The error that occurred during processing.
        """
        # Use configured retry parameters
        message.mark_failed(
            error,
            base_delay_seconds=self.retry_config["base_delay_seconds"],
            max_retries=self.retry_config["max_attempts"],
        )

    def _should_retry_message(self, message: Outbox) -> bool:
        """
        Check if a message should be retried based on configuration.

        Args:
            message (Outbox): The message to check.

        Returns:
            bool: True if the message should be retried, False otherwise.
        """
        return message.retry_count < self.retry_config["max_attempts"]

    def _calculate_retry_delay(self, retry_count: int) -> int:
        """
        Calculate retry delay using configured parameters.

        Args:
            retry_count (int): Current retry attempt number.

        Returns:
            int: Delay in seconds until next retry.
        """
        import random

        base_delay = self.retry_config["base_delay_seconds"]
        multiplier = self.retry_config["backoff_multiplier"]
        max_backoff = self.retry_config["max_backoff_seconds"]
        jitter_enabled = self.retry_config["jitter"]
        jitter_factor = self.retry_config["jitter_factor"]

        # Calculate exponential backoff
        delay = min(base_delay * (multiplier**retry_count), max_backoff)

        # Add jitter if enabled (±25% randomization)
        if jitter_enabled:
            jitter = delay * jitter_factor
            delay = delay + random.uniform(-jitter, jitter)
            delay = max(delay, 1)  # Ensure minimum 1 second delay

        return int(delay)

    def get_retry_config(self) -> dict:
        """
        Get the current retry configuration.

        Returns:
            dict: Current retry configuration parameters.
        """
        return self.retry_config.copy()
