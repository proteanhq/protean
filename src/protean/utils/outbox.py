import traceback
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

from protean.core.aggregate import BaseAggregate
from protean import fields
from protean.utils.eventing import Metadata


class OutboxStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"  # To prevent concurrent processing
    PUBLISHED = "published"
    FAILED = "failed"
    ABANDONED = "abandoned"  # Max retries exceeded


class Outbox(BaseAggregate):
    """
    Outbox is a collection of messages that are to be sent to the event store.
    """

    # Fields to be pushed to broker
    source_id = fields.String(required=True)
    stream_name = fields.String(required=True)
    type = fields.String(required=True)
    data = fields.Dict(required=True)
    metadata = fields.ValueObject(Metadata, required=True)
    created_at = fields.DateTime(default=lambda: datetime.now(timezone.utc))
    published_at = fields.DateTime()
    retry_count = fields.Integer(default=0)

    # Last processed timestamp and error details
    last_processed_at = fields.DateTime()
    last_error = fields.Dict()

    status = fields.String(choices=OutboxStatus, default=OutboxStatus.PENDING.value)

    # Maximum retry attempts before abandoning
    max_retries = fields.Integer(default=3)

    # When to attempt next retry (for exponential backoff)
    next_retry_at = fields.DateTime()

    # Lock mechanism to prevent concurrent processing
    locked_until = fields.DateTime()
    locked_by = fields.String()  # Worker/process identifier

    # For maintaining message order within a stream
    sequence_number = fields.Integer()

    # For distributed tracing
    correlation_id = fields.String()
    trace_id = fields.String()

    # Message priority for processing order
    priority = fields.Integer(default=0)  # Higher = more important

    # Aggregate methods that encapsulate changes
    @classmethod
    def create_message(
        cls,
        source_id: str,
        stream_name: str,
        message_type: str,
        data: dict,
        metadata: Metadata,
        priority: int = 0,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        max_retries: int = 3,
        sequence_number: Optional[int] = None,
    ) -> "Outbox":
        """Create a new outbox message ready for publishing.

        Args:
            source_id: The aggregate ID that generated this message
            stream_name: Target stream/topic for the message
            message_type: Type of the message (event/command name)
            data: Message payload
            metadata: Message metadata
            priority: Processing priority (higher = more important)
            correlation_id: Correlation identifier for tracing
            trace_id: Trace identifier for distributed tracing
            max_retries: Maximum retry attempts
            sequence_number: Sequence number for ordering

        Returns:
            New Outbox instance
        """
        return cls(
            source_id=source_id,
            stream_name=stream_name,
            type=message_type,
            data=data,
            metadata=metadata,
            priority=priority,
            correlation_id=correlation_id,
            trace_id=trace_id,
            max_retries=max_retries,
            sequence_number=sequence_number,
            status=OutboxStatus.PENDING.value,
        )

    def start_processing(self, worker_id: str, lock_duration_minutes: int = 5) -> bool:
        """Attempt to acquire lock and start processing the message.

        Args:
            worker_id: Identifier of the worker processing this message
            lock_duration_minutes: How long to hold the lock

        Returns:
            True if lock acquired successfully, False otherwise
        """
        # Check if message is eligible for processing
        if self.status not in [OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]:
            return False

        if self._is_locked() or not self._can_retry():
            return False

        # Check if enough time has passed for retry
        if self.next_retry_at and datetime.now(timezone.utc) < self.next_retry_at:
            return False

        # Acquire lock and mark as processing
        self.status = OutboxStatus.PROCESSING.value
        self.locked_by = worker_id
        self.locked_until = datetime.now(timezone.utc) + timedelta(
            minutes=lock_duration_minutes
        )
        self.last_processed_at = datetime.now(timezone.utc)
        return True

    def mark_published(self) -> None:
        """Mark message as successfully published."""
        self.status = OutboxStatus.PUBLISHED.value
        self.published_at = datetime.now(timezone.utc)
        self.last_processed_at = datetime.now(timezone.utc)
        self.last_error = None
        # Clear lock
        self._clear_lock()

    def mark_failed(self, error: Exception, base_delay_seconds: int = 60) -> None:
        """Mark processing as failed and schedule retry if applicable.

        Args:
            error: The error that occurred during processing
            base_delay_seconds: Base delay for exponential backoff
        """
        self.retry_count += 1
        self.last_processed_at = datetime.now(timezone.utc)
        self.last_error = {
            "message": str(error),
            "traceback": traceback.format_exc(),
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": self.retry_count,
        }

        # Clear lock
        self._clear_lock()

        # Determine next action based on retry eligibility
        if self._can_retry():
            self.status = OutboxStatus.FAILED.value
            self._calculate_next_retry(base_delay_seconds)
        else:
            # Max retries exceeded
            self.status = OutboxStatus.ABANDONED.value
            self.last_error["reason"] = "Max retries exceeded"

    def mark_abandoned(self, reason: str) -> None:
        """Mark message as permanently failed.

        Args:
            reason: Reason for abandoning the message
        """
        self.status = OutboxStatus.ABANDONED.value
        self.last_error = {
            "message": reason,
            "abandoned_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": self.retry_count,
            "reason": "Manually abandoned",
        }
        self._clear_lock()

    def reset_for_retry(self) -> bool:
        """Reset message status to allow retry (for manual intervention).

        Returns:
            True if reset was successful, False if not eligible
        """
        if self.status not in [OutboxStatus.FAILED.value, OutboxStatus.ABANDONED.value]:
            return False

        self.status = OutboxStatus.PENDING.value
        self.next_retry_at = None
        self._clear_lock()
        return True

    def update_priority(self, new_priority: int) -> None:
        """Update message priority for reordering.

        Args:
            new_priority: New priority value (higher = more important)
        """
        if self.status in [OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]:
            self.priority = new_priority

    def is_ready_for_processing(self) -> bool:
        """Check if message is ready to be processed now.

        Returns:
            True if message can be processed immediately
        """
        if self.status not in [OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]:
            return False

        if self._is_locked() or not self._can_retry():
            return False

        # Check if enough time has passed for retry
        if self.next_retry_at and datetime.now(timezone.utc) < self.next_retry_at:
            return False

        return True

    # Private helper methods
    def _is_locked(self) -> bool:
        """Check if message is currently locked for processing."""
        return (
            self.locked_until
            and datetime.now(timezone.utc) < self.locked_until
            and self.status == OutboxStatus.PROCESSING.value
        )

    def _can_retry(self) -> bool:
        """Check if message can be retried."""
        return self.retry_count < self.max_retries

    def _clear_lock(self) -> None:
        """Clear processing lock."""
        self.locked_until = None
        self.locked_by = None

    def _calculate_next_retry(self, base_delay_seconds: int = 60) -> None:
        """Calculate next retry time using exponential backoff."""
        delay = base_delay_seconds * (2**self.retry_count)
        self.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
