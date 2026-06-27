import logging
import traceback
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Annotated, List, Optional, Tuple

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.index import Index
from protean.core.repository import BaseRepository
from protean.fields import Auto
from protean.utils import ensure_utc_aware
from protean.utils.eventing import Metadata
from protean.utils.query import Q


logger = logging.getLogger(__name__)

PAGE_SIZE = 50  # Default page size for fetching messages
DEFAULT_LOCK_DURATION_MINUTES = 5  # How long a claim holds a processing lock


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

    id = Auto(identifier=True)

    # Fields to be pushed to broker.
    #
    # String fields declare ``max_length`` so SQL providers emit ``VARCHAR(N)``
    # instead of ``TEXT`` / ``VARCHAR(MAX)``. Unbounded columns cannot be
    # indexed on SQL Server, require blind prefix lengths on MySQL, and waste
    # storage everywhere. The outbox path needs indexes on exactly these
    # columns. ``data`` and ``metadata_`` stay unbounded JSON blobs.
    #
    # ``message_id`` is a composite Protean message id (headers.id), e.g.
    # ``testdomain::order-<aggregate-id>-3``, not a bare UUID, so it needs the
    # same 255 ceiling as ``stream_name``. Same reasoning applies to
    # ``causation_id`` (holds a parent message id) and ``correlation_id`` (a
    # flexible, often caller-supplied tracing string) below.
    message_id: Annotated[str, Field(max_length=255)]
    stream_name: Annotated[str, Field(max_length=255)]
    type: Annotated[str, Field(max_length=255)]
    data: dict
    metadata_: Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime | None = None
    retry_count: int = 0

    # Last processed timestamp and error details
    last_processed_at: datetime | None = None
    last_error: dict | None = None

    status: Annotated[str, Field(max_length=32)] = OutboxStatus.PENDING.value

    # Maximum retry attempts before abandoning
    max_retries: int = 3

    # When to attempt next retry (for exponential backoff)
    next_retry_at: datetime | None = None

    # Lock mechanism to prevent concurrent processing
    locked_until: datetime | None = None
    # Worker/process identifier
    locked_by: Annotated[str | None, Field(max_length=128)] = None

    # For maintaining message order within a stream
    sequence_number: int | None = None

    # For distributed tracing (see note above: identity-shaped / caller-supplied)
    correlation_id: Annotated[str | None, Field(max_length=255)] = None
    causation_id: Annotated[str | None, Field(max_length=255)] = None

    # Message priority for processing order
    priority: int = 0  # Higher = more important

    # Target broker for this message (None = legacy/unqualified)
    target_broker: Annotated[str | None, Field(max_length=128)] = None

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
        causation_id: Optional[str] = None,
        max_retries: int = 3,
        sequence_number: Optional[int] = None,
        target_broker: str | None = None,
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
            causation_id: Causation identifier (parent message's headers.id)
            max_retries: Maximum retry attempts
            sequence_number: Sequence number for ordering
            target_broker: Name of the broker this message targets (None = legacy)

        Returns:
            New Outbox instance
        """
        return cls(
            message_id=message_id,
            stream_name=stream_name,
            type=message_type,
            data=data,
            metadata_=metadata,
            priority=priority,
            correlation_id=correlation_id,
            causation_id=causation_id,
            max_retries=max_retries,
            sequence_number=sequence_number,
            target_broker=target_broker,
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
        if self.next_retry_at:
            current_time = datetime.now(timezone.utc)
            if current_time < ensure_utc_aware(self.next_retry_at):
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
        if self.next_retry_at:
            current_time = datetime.now(timezone.utc)
            if current_time < ensure_utc_aware(self.next_retry_at):
                return False

        return True

    # Private helper methods
    def _is_locked(self) -> bool:
        """Check if message is currently locked for processing."""
        return bool(
            self.locked_until
            and datetime.now(timezone.utc) < ensure_utc_aware(self.locked_until)
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


# Recommended indexes for the outbox table. Applied when the framework
# registers a per-provider Outbox (see ``DomainInfrastructure.initialize_outbox``).
#
# - The active-set partial index keeps the polling index tiny: only pending and
#   failed rows are indexed, not the published archive (which dominates volume).
# - ``message_id`` is unique for idempotency / find-by-message-id.
# - ``correlation_id`` supports trace-oriented lookups.
OUTBOX_INDEXES = [
    Index(
        "status",
        "priority",
        desc=("priority",),
        where=Q(status__in=[OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]),
        name="ix_outbox_active",
    ),
    Index("message_id", unique=True),
    Index("correlation_id"),
]


class OutboxRepository(BaseRepository):
    """Repository for querying outbox messages with specialized filtering methods."""

    def _apply_limit_and_execute(self, query, limit: Optional[int]):
        """Helper method to apply limit and handle zero limit case."""
        if limit is not None and limit == 0:
            return []

        if limit is not None and limit > 0:
            query = query.limit(limit)

        # The poll path only needs the rows, never the full match count, so
        # skip the adapter's total-count round-trip (a wrapped ``COUNT`` on SQL).
        return query.all(with_total=False).items

    def _eligibility_criteria(
        self, now: datetime, target_broker: str | None = None
    ) -> Q:
        """Build the ``Q`` selecting messages ready for processing.

        A message is eligible when its lock is free (``locked_until`` is null or
        in the past) and its status is one of:

        - ``PENDING`` — never processed;
        - ``FAILED`` — eligible once its retry time has passed;
        - ``PROCESSING`` — only if the lock has **expired**, i.e. a worker
          claimed it and died before finishing. Including these makes a crashed
          claim self-heal: the row becomes claimable again once ``locked_until``
          passes. An actively-locked ``PROCESSING`` row (lock in the future) is
          excluded, so an in-flight message is never stolen.

        When ``target_broker`` is given, only rows destined for that broker
        match. Shared by :meth:`find_unprocessed` and :meth:`claim_batch` so the
        two cannot drift.
        """
        criteria = Q(
            status__in=[
                OutboxStatus.PENDING.value,
                OutboxStatus.FAILED.value,
                OutboxStatus.PROCESSING.value,
            ]
        )
        criteria &= Q(locked_until__isnull=True) | Q(locked_until__lt=now)
        criteria &= Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)
        if target_broker is not None:
            criteria &= Q(target_broker=target_broker)
        return criteria

    def find_unprocessed(
        self,
        limit: Optional[int] = None,
        target_broker: str | None = None,
    ) -> List[Outbox]:
        """Find messages that are ready for processing.

        Returns messages whose lock is free (``locked_until`` null or in the
        past) that are:
        - PENDING, or
        - FAILED and past their retry time, or
        - PROCESSING with an expired lock (a crashed claim, now reclaimable)

        and not expired based on retry count. See :meth:`_eligibility_criteria`.

        Status, lock-window, and retry-window predicates are evaluated at the
        database. The retry-count check (``retry_count < max_retries``) is a
        column-to-column comparison and remains in Python until F() expressions
        land; in practice this filter eliminates near-zero rows on a healthy
        workload.

        Args:
            limit: Maximum number of messages to return
            target_broker: Filter by target broker name. When provided,
                only returns rows destined for this broker.

        Returns:
            List of Outbox messages ready for processing

        Note:
            This is a **read-only** query — it does not lock or claim rows. For
            the processing path, use :meth:`claim_batch`, which atomically
            selects and claims rows in one round trip. ``find_unprocessed`` is
            for inspection and monitoring of the queue.
        """
        # Handle zero limit case
        if limit is not None and limit == 0:
            return []

        now = datetime.now(timezone.utc)
        query = self._dao.query.filter(self._eligibility_criteria(now, target_broker))

        # Order by priority (higher first)
        query = query.order_by("-priority")

        candidates = self._apply_limit_and_execute(query, limit)

        # Final guard: retry_count < max_retries (column-to-column).
        # Pushed to SQL once F() expressions land.
        return [msg for msg in candidates if msg.retry_count < msg.max_retries]

    def claim_batch(
        self,
        worker_id: str,
        limit: int,
        target_broker: str | None = None,
        lock_duration_minutes: int = DEFAULT_LOCK_DURATION_MINUTES,
    ) -> List[Outbox]:
        """Atomically select and claim up to ``limit`` ready messages.

        This is the production claim path. It selects eligible messages and
        marks them ``PROCESSING`` (setting ``locked_by`` and ``locked_until``)
        per the DAO's :meth:`~protean.port.dao.BaseDAO._claim` contract: no two
        workers ever claim the same message. On PostgreSQL this is a single
        ``UPDATE … RETURNING`` statement; other backends use a guarded
        read-then-update that resolves the race without double-claiming.

        Eligibility is defined by :meth:`_eligibility_criteria`: a lock-free
        ``PENDING`` row, a retry-due ``FAILED`` row, or a ``PROCESSING`` row
        whose lock has expired (a crashed claim, reclaimed for self-healing),
        optionally filtered to ``target_broker``.

        Args:
            worker_id: Identifier of the worker claiming the messages.
            limit: Maximum number of messages to claim. ``<= 0`` claims none.
            target_broker: When provided, only claim rows for this broker.
            lock_duration_minutes: How long the processing lock is held.

        Returns:
            The claimed messages, already in ``PROCESSING`` state, ordered by
            priority (higher first).
        """
        if limit <= 0:
            return []

        now = datetime.now(timezone.utc)

        claimed = self._dao._claim(
            criteria=self._eligibility_criteria(now, target_broker),
            claim_fields={
                "status": OutboxStatus.PROCESSING.value,
                "locked_by": worker_id,
                "locked_until": now + timedelta(minutes=lock_duration_minutes),
                "last_processed_at": now,
            },
            limit=limit,
            order_by="-priority",
        )

        # Defense-in-depth guard: retry_count < max_retries (column-to-column,
        # stays in Python until F() expressions land). By the FAILED/ABANDONED
        # invariant a claimable row always satisfies this, so it excludes no
        # claimed row in practice.
        ready = [msg for msg in claimed if msg.retry_count < msg.max_retries]

        # An excluded row has already been marked PROCESSING by the claim, so it
        # would sit locked until ``locked_until`` expires. This only happens if
        # the FAILED/ABANDONED invariant is violated upstream — surface it.
        if len(ready) != len(claimed):
            logger.warning(
                "outbox.claimed_rows_excluded_by_retry_guard",
                extra={"claimed": len(claimed), "returned": len(ready)},
            )

        return ready

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

    def find_by_causation_id(
        self, causation_id: str, limit: Optional[int] = PAGE_SIZE
    ) -> List[Outbox]:
        """Find messages caused by a specific parent message.

        Args:
            causation_id: Causation ID (parent message's headers.id) to filter by
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages caused by the given message
        """
        query = self._dao.query.filter(causation_id=causation_id)
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
        return {
            status.value: self._dao.query.filter(status=status.value).count()
            for status in OutboxStatus
        }

    def _cleanup_batch_size(self) -> int:
        """Resolve the cleanup batch size from ``[outbox.cleanup]`` config.

        Reads from the repository's own domain (not the ``current_domain``
        global) so cleanup works in standalone/cron usage with no active domain
        context. Defaults to 5000 when unset, matching ``domain.config``.
        """
        return (
            self._dao.domain.config.get("outbox", {})
            .get("cleanup", {})
            .get("batch_size", 5000)
        )

    def _delete_in_batches(self, criteria: Q, batch_size: Optional[int]) -> int:
        """Delete all rows matching ``criteria`` in bounded batches.

        Loops :meth:`BaseDAO._delete_top` until a batch deletes fewer than
        ``batch_size`` rows (the table is drained). When called outside a Unit
        of Work each batch commits before the next begins, so a large backlog
        is cleared without one long-held lock or an oversized transaction.
        """
        if batch_size is None:
            batch_size = self._cleanup_batch_size()

        total = 0
        while True:
            deleted = self._dao._delete_top(criteria, limit=batch_size)
            total += deleted
            if deleted < batch_size:
                break
        return total

    def cleanup_old_published(
        self, older_than_hours: int = 168, batch_size: Optional[int] = None
    ) -> int:
        """Clean up published messages older than specified hours.

        Args:
            older_than_hours: Age in hours after which published messages should be cleaned up
            batch_size: Rows to delete per batch. Defaults to the
                ``[outbox.cleanup]`` config value (5000).

        Returns:
            Number of messages deleted
        """
        threshold_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

        return self._delete_in_batches(
            Q(status=OutboxStatus.PUBLISHED.value, published_at__lt=threshold_time),
            batch_size,
        )

    def cleanup_old_abandoned(
        self, older_than_hours: int = 720, batch_size: Optional[int] = None
    ) -> int:
        """Clean up abandoned messages older than specified hours.

        Abandoned messages remain in the table for observability but can be cleaned up
        after a reasonable retention period (default 30 days).

        Args:
            older_than_hours: Age in hours after which abandoned messages should be cleaned up (default: 720 = 30 days)
            batch_size: Rows to delete per batch. Defaults to the
                ``[outbox.cleanup]`` config value (5000).

        Returns:
            Number of messages deleted
        """
        threshold_time = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

        return self._delete_in_batches(
            Q(
                status=OutboxStatus.ABANDONED.value,
                last_processed_at__lt=threshold_time,
            ),
            batch_size,
        )

    def cleanup_old_messages(
        self,
        published_retention_hours: int = 168,
        abandoned_retention_hours: int = 720,
        batch_size: Optional[int] = None,
    ) -> dict:
        """Clean up old published and abandoned messages based on retention periods.

        This method cleans up both published and abandoned messages that are older
        than their respective retention periods.

        Args:
            published_retention_hours: Age in hours after which published messages should be cleaned up (default: 168 = 7 days)
            abandoned_retention_hours: Age in hours after which abandoned messages should be cleaned up (default: 720 = 30 days)
            batch_size: Rows to delete per batch. Defaults to the
                ``[outbox.cleanup]`` config value (5000).

        Returns:
            dict: Number of messages deleted by status {'published': count, 'abandoned': count, 'total': total_count}
        """
        published_count = self.cleanup_old_published(
            older_than_hours=published_retention_hours, batch_size=batch_size
        )
        abandoned_count = self.cleanup_old_abandoned(
            older_than_hours=abandoned_retention_hours, batch_size=batch_size
        )

        total_count = published_count + abandoned_count

        return {
            "published": published_count,
            "abandoned": abandoned_count,
            "total": total_count,
        }
