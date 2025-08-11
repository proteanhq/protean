import traceback
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import List, Optional, Tuple

from protean.core.aggregate import BaseAggregate
from protean.core.repository import BaseRepository
from protean import fields
from protean.utils.eventing import Metadata


PAGE_SIZE = 50  # Default page size for fetching messages


class OutboxStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"  # To prevent concurrent processing
    PUBLISHED = "published"
    FAILED = "failed"
    ABANDONED = "abandoned"  # Max retries exceeded


class ProcessingResult(Enum):
    SUCCESS = "success"
    NOT_ELIGIBLE = "not_eligible"
    ALREADY_LOCKED = "already_locked"
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"
    RETRY_NOT_DUE = "retry_not_due"


class Outbox(BaseAggregate):
    """
    Outbox is a collection of messages that are to be sent to the event store.
    """

    # Fields to be pushed to broker
    message_id = fields.String(required=True)
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
        message_id: str,
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
            message_id: The unique message ID that generated this message
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
            message_id=message_id,
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

    def start_processing(
        self, worker_id: str, lock_duration_minutes: int = 5
    ) -> Tuple[bool, ProcessingResult]:
        """Attempt to acquire lock and start processing the message.

        Args:
            worker_id: Identifier of the worker processing this message
            lock_duration_minutes: How long to hold the lock

        Returns:
            Tuple of (success: bool, result: ProcessingResult) indicating outcome
        """
        # Check if message is locked first (for PROCESSING status)
        if self._is_locked():
            return False, ProcessingResult.ALREADY_LOCKED

        # Check if message is eligible for processing
        if self.status not in [OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]:
            return False, ProcessingResult.NOT_ELIGIBLE

        if not self._can_retry():
            return False, ProcessingResult.MAX_RETRIES_EXCEEDED

        # Check if enough time has passed for retry
        if self.next_retry_at and datetime.now(timezone.utc) < self.next_retry_at:
            return False, ProcessingResult.RETRY_NOT_DUE

        # Acquire lock and mark as processing
        self.status = OutboxStatus.PROCESSING.value
        self.locked_by = worker_id
        self.locked_until = datetime.now(timezone.utc) + timedelta(
            minutes=lock_duration_minutes
        )
        self.last_processed_at = datetime.now(timezone.utc)
        return True, ProcessingResult.SUCCESS

    def mark_published(self) -> None:
        """Mark message as successfully published."""
        self.status = OutboxStatus.PUBLISHED.value
        self.published_at = datetime.now(timezone.utc)
        self.last_processed_at = datetime.now(timezone.utc)
        self.last_error = None
        # Clear lock
        self._clear_lock()

    def mark_failed(
        self,
        error: Exception,
        base_delay_seconds: int = 60,
        max_retries: Optional[int] = None,
    ) -> None:
        """Mark processing as failed and schedule retry if applicable.

        Args:
            error: The error that occurred during processing
            base_delay_seconds: Base delay for exponential backoff
            max_retries: Override max retries (uses self.max_retries if None)
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

        # Use provided max_retries or fall back to instance max_retries
        effective_max_retries = (
            max_retries if max_retries is not None else self.max_retries
        )

        # Determine next action based on retry eligibility
        if self.retry_count < effective_max_retries:
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

    def _calculate_next_retry(
        self, base_delay_seconds: int = 60, max_backoff_seconds: int = 3600
    ) -> None:
        """Calculate next retry time using exponential backoff.
        Args:
            base_delay_seconds: Base delay in seconds for the backoff calculation.
            max_backoff_seconds: Maximum allowable delay in seconds to cap the backoff.
        """
        delay = min(base_delay_seconds * (2**self.retry_count), max_backoff_seconds)
        self.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)


class OutboxRepository(BaseRepository):
    """Repository for querying outbox messages with specialized filtering methods."""

    def _apply_limit_and_execute(self, query, limit: Optional[int]):
        """Helper method to apply limit and handle zero limit case."""
        if limit is not None and limit == 0:
            return []

        if limit is not None and limit > 0:
            query = query.limit(limit)

        return query.all().items

    def find_unprocessed(self, limit: Optional[int] = None) -> List[Outbox]:
        """Find messages that are ready for processing.

        Returns messages that are:
        - PENDING status OR
        - FAILED status and past retry time
        - Not locked
        - Not expired based on retry count

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages ready for processing
        """
        # Handle zero limit case
        if limit is not None and limit == 0:
            return []

        query = self._dao.query.filter(
            status__in=[OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]
        )

        # Order by priority (higher first)
        query = query.order_by("-priority")

        # Apply larger limit for initial query since we'll filter afterwards
        # If a specific limit is requested, fetch more to account for filtering
        query_limit = None
        if limit is not None and limit > 0:
            # Fetch more records to account for filtering, but cap it reasonably
            query_limit = min(limit * 3, 1000)

        results = self._apply_limit_and_execute(query, query_limit)

        # Filter out messages that are not ready for processing
        # (locked, not past retry time, or exceeded max retries)
        # Keep the original ordering from the database query
        ready_messages = [msg for msg in results if msg.is_ready_for_processing()]

        # Apply the actual limit to the filtered results
        if limit is not None and limit > 0:
            ready_messages = ready_messages[:limit]

        return ready_messages

    def find_failed(self, limit: Optional[int] = PAGE_SIZE) -> List[Outbox]:
        """Find messages that have failed processing.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages in FAILED status
        """
        query = self._dao.query.filter(status=OutboxStatus.FAILED.value)
        query = query.order_by("-last_processed_at")

        return self._apply_limit_and_execute(query, limit)

    def find_abandoned(self, limit: Optional[int] = PAGE_SIZE) -> List[Outbox]:
        """Find messages that have been abandoned.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages in ABANDONED status
        """
        query = self._dao.query.filter(status=OutboxStatus.ABANDONED.value)
        query = query.order_by("-last_processed_at")

        return self._apply_limit_and_execute(query, limit)

    def find_published(self, limit: Optional[int] = PAGE_SIZE) -> List[Outbox]:
        """Find messages that have been successfully published.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages in PUBLISHED status
        """
        query = self._dao.query.filter(status=OutboxStatus.PUBLISHED.value)
        query = query.order_by("-published_at")

        return self._apply_limit_and_execute(query, limit)

    def find_processing(self, limit: Optional[int] = PAGE_SIZE) -> List[Outbox]:
        """Find messages that are currently being processed.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages in PROCESSING status
        """
        query = self._dao.query.filter(status=OutboxStatus.PROCESSING.value)
        query = query.order_by("-last_processed_at")

        return self._apply_limit_and_execute(query, limit)

    def find_by_stream(
        self, stream_name: str, limit: Optional[int] = PAGE_SIZE
    ) -> List[Outbox]:
        """Find messages for a specific stream.

        Args:
            stream_name: Name of the stream to filter by
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages for the given stream
        """
        query = self._dao.query.filter(stream_name=stream_name)
        query = query.order_by("-created_at")

        return self._apply_limit_and_execute(query, limit)

    def find_by_message_id(self, message_id: str) -> Optional[Outbox]:
        """Find a message by its unique message ID.

        Args:
            message_id: The unique message ID

        Returns:
            The Outbox message with the given message ID, or None if not found
        """
        query = self._dao.query.filter(message_id=message_id)
        results = query.all().items
        return results[0] if results else None

    def find_by_message_type(
        self, message_type: str, limit: Optional[int] = PAGE_SIZE
    ) -> List[Outbox]:
        """Find messages of a specific type.

        Args:
            message_type: Type of the message (event/command name)
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages of the given type
        """
        query = self._dao.query.filter(type=message_type)
        query = query.order_by("-created_at")

        return self._apply_limit_and_execute(query, limit)

    def find_by_priority(
        self, min_priority: int = 1, limit: Optional[int] = PAGE_SIZE
    ) -> List[Outbox]:
        """Find messages with priority greater than or equal to the specified value.

        Args:
            min_priority: Minimum priority value (default: 1 for high priority messages)
            limit: Maximum number of messages to return (default: PAGE_SIZE)

        Returns:
            List of Outbox messages with priority >= min_priority
        """
        query = self._dao.query.filter(priority__gte=min_priority)
        query = query.order_by("-priority")

        return self._apply_limit_and_execute(query, limit)

    def find_by_correlation_id(
        self, correlation_id: str, limit: Optional[int] = PAGE_SIZE
    ) -> List[Outbox]:
        """Find messages with a specific correlation ID.

        Args:
            correlation_id: Correlation ID to filter by
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages with the given correlation ID
        """
        query = self._dao.query.filter(correlation_id=correlation_id)
        query = query.order_by("-created_at")

        return self._apply_limit_and_execute(query, limit)

    def find_stale_processing(self, stale_threshold_minutes: int = 10) -> List[Outbox]:
        """Find messages that have been processing for too long (stale locks).

        Args:
            stale_threshold_minutes: Minutes after which a processing message is considered stale

        Returns:
            List of Outbox messages that are stale
        """
        threshold_time = datetime.now(timezone.utc) - timedelta(
            minutes=stale_threshold_minutes
        )

        query = self._dao.query.filter(
            status=OutboxStatus.PROCESSING.value, last_processed_at__lt=threshold_time
        )
        query = query.order_by("last_processed_at")

        return query.all().items

    def find_recent(
        self, hours: int = 24, limit: Optional[int] = PAGE_SIZE
    ) -> List[Outbox]:
        """Find messages created within the specified number of hours.

        Args:
            hours: Number of hours to look back
            limit: Maximum number of messages to return

        Returns:
            List of recent Outbox messages
        """
        threshold_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        query = self._dao.query.filter(created_at__gte=threshold_time)
        query = query.order_by("-created_at")

        return self._apply_limit_and_execute(query, limit)

    def find_retry_ready(self, limit: Optional[int] = PAGE_SIZE) -> List[Outbox]:
        """Find failed messages that are ready for retry.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages ready for retry
        """
        current_time = datetime.now(timezone.utc)

        query = self._dao.query.filter(
            status=OutboxStatus.FAILED.value, next_retry_at__lte=current_time
        ).order_by("-priority")

        return self._apply_limit_and_execute(query, limit)

    def count_by_status(self) -> dict:
        """Get count of messages by their status.

        Returns:
            Dictionary with status as key and count as value
        """
        counts = {}

        for status in OutboxStatus:
            results = self._dao.query.filter(status=status.value).all()
            counts[status.value] = len(results)

        return counts

    def cleanup_old_published(self, older_than_hours: int = 168) -> int:
        """Clean up published messages older than specified hours.

        Args:
            older_than_hours: Age in hours after which published messages should be cleaned up

        Returns:
            Number of messages deleted
        """
        threshold_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

        query = self._dao.query.filter(
            status=OutboxStatus.PUBLISHED.value, published_at__lt=threshold_time
        )

        # Get count before deletion
        messages_to_delete = query.all()
        count = len(messages_to_delete)

        # Delete the messages
        query.delete_all()

        return count

    def cleanup_old_abandoned(self, older_than_hours: int = 720) -> int:
        """Clean up abandoned messages older than specified hours.

        Abandoned messages remain in the table for observability but can be cleaned up
        after a reasonable retention period (default 30 days).

        Args:
            older_than_hours: Age in hours after which abandoned messages should be cleaned up (default: 720 = 30 days)

        Returns:
            Number of messages deleted
        """
        threshold_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

        query = self._dao.query.filter(
            status=OutboxStatus.ABANDONED.value, last_processed_at__lt=threshold_time
        )

        # Get count before deletion
        messages_to_delete = query.all()
        count = len(messages_to_delete)

        # Delete the messages
        query.delete_all()

        return count

    def cleanup_old_messages(
        self, published_retention_hours: int = 168, abandoned_retention_hours: int = 720
    ) -> dict:
        """Clean up old published and abandoned messages based on retention periods.

        This method cleans up both published and abandoned messages that are older
        than their respective retention periods.

        Args:
            published_retention_hours: Age in hours after which published messages should be cleaned up (default: 168 = 7 days)
            abandoned_retention_hours: Age in hours after which abandoned messages should be cleaned up (default: 720 = 30 days)

        Returns:
            dict: Number of messages deleted by status {'published': count, 'abandoned': count, 'total': total_count}
        """
        published_count = self.cleanup_old_published(
            older_than_hours=published_retention_hours
        )
        abandoned_count = self.cleanup_old_abandoned(
            older_than_hours=abandoned_retention_hours
        )

        total_count = published_count + abandoned_count

        return {
            "published": published_count,
            "abandoned": abandoned_count,
            "total": total_count,
        }
