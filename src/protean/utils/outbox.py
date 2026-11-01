import logging
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, cast

from pydantic import BeforeValidator, Field

if TYPE_CHECKING:
    from protean.core.event import BaseEvent
    from protean.core.queryset import QuerySet

from protean.core.aggregate import BaseAggregate
from protean.core.index import Index
from protean.core.repository import BaseRepository
from protean.exceptions import DeserializationError, ValidationError
from protean.fields import Auto
from protean.port.dao import HoldBack
from protean.utils import (
    DomainObjects,
    OptionalStdlibDatetime,
    StdlibDatetime,
    ensure_utc_aware,
    fqn,
    outbox_trace,
)
from protean.utils.eventing import Metadata
from protean.utils.globals import _domain_now
from protean.utils.query import F, Q

logger = logging.getLogger(__name__)

PAGE_SIZE = 50  # Default page size for fetching messages
DEFAULT_LOCK_DURATION_MINUTES = 5  # How long a claim holds a processing lock

# Fallback broker name for an outbox row whose target broker is unspecified.
# Matches the UnitOfWork default (``outbox_config.get("broker", "default")``).
DEFAULT_TARGET_BROKER = "default"

# Reserved stream suffix that a partition key can never equal (ADR-0028
# decision 3). ``backfill`` is configurable via ``[server.priority_lanes]``;
# ``dlq`` is fixed, so it lives here as the constant half of the reserved set.
RESERVED_DLQ_TOKEN = "dlq"

# Max length of a partition key. Mirrors the ``Outbox.partition_key`` field
# ceiling so an over-long key is rejected up front with a clear reason rather
# than tripping the generic ``MaxLengthValidator`` deep inside ``create_message``.
MAX_PARTITION_KEY_LENGTH = 255


def invalid_partition_key_reason(
    partition_key: str | None, backfill_suffix: str
) -> str | None:
    """Return why *partition_key* cannot be used for partition routing, or ``None``.

    A key is rejected when it is empty, longer than ``MAX_PARTITION_KEY_LENGTH``,
    contains a colon, equals ``"dlq"`` or *backfill_suffix*, or has the
    ``__name__`` form (see ADR-0028).

    Args:
        backfill_suffix: The configured ``[server.priority_lanes]``
            ``backfill_suffix``.
    """
    if not partition_key:
        return "partition key is null or empty"
    if len(partition_key) > MAX_PARTITION_KEY_LENGTH:
        return (
            f"partition key exceeds {MAX_PARTITION_KEY_LENGTH} characters "
            f"(got {len(partition_key)})"
        )
    if ":" in partition_key:
        return "partition key contains a colon"
    if partition_key in (RESERVED_DLQ_TOKEN, backfill_suffix):
        return f"partition key '{partition_key}' is a reserved lane/DLQ token"
    if (
        len(partition_key) >= 4
        and partition_key.startswith("__")
        and partition_key.endswith("__")
    ):
        return (
            f"partition key '{partition_key}' uses the reserved "
            "'__name__' sentinel form"
        )
    return None


def _coerce_target_broker(value: Any) -> Any:
    """Coerce a NULL ``target_broker`` to the default broker name.

    The column is NOT NULL, but outbox rows written before the field was
    populated may hold NULL. Coercing on read lets those legacy rows load
    while keeping the (message_id, target_broker) unique guarantee intact for
    new rows.
    """
    return DEFAULT_TARGET_BROKER if value is None else value


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
    # columns. ``data`` stays an unbounded JSON column, and SQL providers store
    # ``metadata_`` as a pickled blob.
    #
    # ``message_id`` is a composite Protean message id (headers.id), e.g.
    # ``testdomain::order-<aggregate-id>-3``, not a bare UUID, so it needs the
    # same 255 ceiling as ``stream_name``. Same reasoning applies to
    # ``causation_id`` (holds a parent message id) and ``correlation_id`` (a
    # flexible, often caller-supplied tracing string) below.
    message_id: Annotated[str, Field(max_length=255)]
    stream_name: Annotated[str, Field(max_length=255)]
    type: Annotated[str, Field(max_length=255)]
    data: dict[str, Any]
    metadata_: Metadata
    # Out of scope for the injectable clock (issue 9.1.7): a default_factory runs
    # at field-definition time with no ``now`` argument and no reliable domain
    # context, and this is a creation timestamp (aggregate identity), not a
    # deadline/lock boundary. Left as real UTC deliberately.
    created_at: StdlibDatetime = Field(default_factory=lambda: datetime.now(UTC))
    published_at: OptionalStdlibDatetime = None
    retry_count: int = 0

    # Last processed timestamp and error details
    last_processed_at: OptionalStdlibDatetime = None
    last_error: dict[str, Any] | None = None

    status: Annotated[str, Field(max_length=32)] = OutboxStatus.PENDING.value

    # Maximum retry attempts before abandoning
    max_retries: int = 3

    # When to attempt next retry (for exponential backoff)
    next_retry_at: OptionalStdlibDatetime = None

    # Lock mechanism to prevent concurrent processing
    locked_until: OptionalStdlibDatetime = None
    # Worker/process identifier
    locked_by: Annotated[str | None, Field(max_length=128)] = None

    # The event's position within its Unit of Work commit (0, 1, 2, ...),
    # written by the Unit of Work. Breaks ties on ``created_at`` so rows of one
    # commit claim in event order. ``None`` on rows written before it was set.
    sequence_number: int | None = None

    # For distributed tracing (see note above: identity-shaped / caller-supplied)
    correlation_id: Annotated[str | None, Field(max_length=255)] = None
    causation_id: Annotated[str | None, Field(max_length=255)] = None

    # Partition key for per-key sequential routing (ADR-0028). Denormalized
    # off the event payload at record creation for a handler category that
    # declares ``sequential_by``; ``None`` for non-partitioned categories. The
    # outbox processor routes a row with this set to ``{stream_category}:{key}``
    # when the target broker advertises ``STREAM_PARTITIONING``. The framework's
    # write path (the Unit of Work) validates the key before storing it, so a
    # row written through the framework never carries a colon or a reserved
    # token; a directly constructed row (tests, legacy data) is a backstop the
    # outbox processor re-checks and abandons at publish.
    partition_key: Annotated[str | None, Field(max_length=MAX_PARTITION_KEY_LENGTH)] = (
        None
    )

    # The stream category the row publishes to, copied from
    # ``metadata.domain.stream_category`` when the row is written. The claim
    # groups partitioned rows by it, so a key's later rows wait for its earlier
    # ones (ADR-0028). ``None`` on rows written before it was set; such a row
    # is claimed as if it had no partition key.
    stream_category: Annotated[str | None, Field(max_length=255)] = None

    # Message priority for processing order
    priority: int = 0  # Higher = more important

    # Target broker this message is destined for. The framework always sets it
    # on write (the internal broker name, or an external broker name); the
    # composite (message_id, target_broker) unique index depends on it being
    # non-NULL, so the column is NOT NULL. Legacy rows written before the field
    # was populated are coerced from NULL to the default broker name on read.
    # This field is intentionally required (NOT NULL) and must not be given a
    # default.
    target_broker: Annotated[
        str, BeforeValidator(_coerce_target_broker), Field(max_length=128)
    ]

    @classmethod
    def create_message(
        cls,
        message_id: str,
        stream_name: str,
        message_type: str,
        data: dict[str, Any],
        metadata: Metadata,
        priority: int = 0,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        max_retries: int = 3,
        sequence_number: int | None = None,
        target_broker: str = DEFAULT_TARGET_BROKER,
        partition_key: str | None = None,
        stream_category: str | None = None,
    ) -> "Outbox":
        """Return a new outbox message in ``PENDING`` status.

        Args:
            priority: Higher values are processed first.
            causation_id: The ``headers.id`` of the message that caused this one.
            max_retries: Maximum retry attempts.
            sequence_number: The event's position within its commit. Orders rows
                that share ``priority`` and ``created_at``.
            target_broker: The broker the row is published to. Defaults to
                ``"default"``, not the configured internal broker.
            partition_key: The key that routes the row to its partition
                (ADR-0028), or ``None`` for a category without one. The caller
                checks it with ``invalid_partition_key_reason`` first.
            stream_category: The event's ``metadata.domain.stream_category``.
                The claim groups partitioned rows by it.
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
            partition_key=partition_key,
            stream_category=stream_category,
            status=OutboxStatus.PENDING.value,
        )

    def start_processing(
        self,
        worker_id: str,
        lock_duration_minutes: int = 5,
        now: datetime | None = None,
    ) -> tuple[bool, ProcessingResult]:
        """Attempt to acquire lock and start processing the message.

        Args:
            worker_id: Identifier of the worker processing this message
            lock_duration_minutes: How long to hold the lock
            now: Reference time for the lock/retry comparisons. Defaults to the
                active domain's clock (or real UTC with no context). A single
                reading is used for every comparison and timestamp below so the
                lock window is computed against one consistent instant.

        Returns:
            Tuple of (success: bool, result: ProcessingResult) indicating outcome
        """
        now = _domain_now(now)

        # Check if message is locked first (for PROCESSING status)
        if self._is_locked(now):
            return False, ProcessingResult.ALREADY_LOCKED

        # Check if message is eligible for processing
        if self.status not in [OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]:
            return False, ProcessingResult.NOT_ELIGIBLE

        if not self._can_retry():
            return False, ProcessingResult.MAX_RETRIES_EXCEEDED

        # Check if enough time has passed for retry
        if self.next_retry_at and now < ensure_utc_aware(self.next_retry_at):
            return False, ProcessingResult.RETRY_NOT_DUE

        # Acquire lock and mark as processing
        self.status = OutboxStatus.PROCESSING.value
        self.locked_by = worker_id
        self.locked_until = now + timedelta(minutes=lock_duration_minutes)
        self.last_processed_at = now
        return True, ProcessingResult.SUCCESS

    def mark_published(self, now: datetime | None = None) -> None:
        """Mark message as successfully published.

        Args:
            now: Timestamp to record. Defaults to the active domain's clock.
        """
        now = _domain_now(now)
        self.status = OutboxStatus.PUBLISHED.value
        self.published_at = now
        self.last_processed_at = now
        self.last_error = None
        # Clear lock
        self._clear_lock()

    def mark_failed(
        self,
        error: Exception,
        base_delay_seconds: int = 60,
        max_retries: int | None = None,
        now: datetime | None = None,
    ) -> None:
        """Mark processing as failed and schedule retry if applicable.

        Args:
            error: The error that occurred during processing
            base_delay_seconds: Base delay for exponential backoff
            max_retries: Override max retries (uses self.max_retries if None)
            now: Reference time for the failure timestamp and the retry-backoff
                schedule. Defaults to the active domain's clock.
        """
        now = _domain_now(now)
        self.retry_count += 1
        self.last_processed_at = now
        self.last_error = {
            "message": str(error),
            "traceback": traceback.format_exc(),
            "failed_at": now.isoformat(),
            "retry_count": self.retry_count,
        }

        # Clear lock
        self._clear_lock()

        # Use provided max_retries or fall back to instance max_retries
        effective_max_retries = (
            max_retries if max_retries is not None else self.max_retries
        )
        # The claim compares ``retry_count`` with the row's ``max_retries``
        # column. Store the threshold used here so a row kept FAILED stays
        # claimable. Otherwise a configured ``max_attempts`` above the column
        # would leave the row FAILED and never claimed, and it would halt its
        # partition key with no ABANDONED row to show why.
        self.max_retries = effective_max_retries

        # Determine next action based on retry eligibility
        if self.retry_count < effective_max_retries:
            self.status = OutboxStatus.FAILED.value
            self._calculate_next_retry(base_delay_seconds, now=now)
        else:
            # Max retries exceeded
            self.status = OutboxStatus.ABANDONED.value
            self.last_error["reason"] = "Max retries exceeded"

    def mark_abandoned(
        self,
        reason: str,
        now: datetime | None = None,
        cause: str = "Manually abandoned",
    ) -> None:
        """Mark message as permanently failed.

        Args:
            reason: Reason for abandoning the message
            now: Timestamp to record. Defaults to the active domain's clock.
            cause: Short label for what abandoned the row, stored as
                ``last_error["reason"]``.
        """
        now = _domain_now(now)
        self.status = OutboxStatus.ABANDONED.value
        self.last_processed_at = now
        self.last_error = {
            "message": reason,
            "abandoned_at": now.isoformat(),
            "retry_count": self.retry_count,
            "reason": cause,
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

    def release(self) -> bool:
        """Give a claimed row back unpublished, as if it had not been claimed.

        The outbox processor calls this on the later rows of a group in a batch
        after an earlier row of that group fails to publish, so that they wait
        for it. The row goes back to ``PENDING`` with its lock cleared.
        ``retry_count`` and ``next_retry_at`` are left as they are, because the
        row itself did not fail.

        Returns:
            True if the row was released, False if it was not ``PROCESSING``
            (nothing is changed then)
        """
        if self.status != OutboxStatus.PROCESSING.value:
            return False

        self.status = OutboxStatus.PENDING.value
        self._clear_lock()
        return True

    def update_priority(self, new_priority: int) -> None:
        """Update message priority for reordering.

        Args:
            new_priority: New priority value (higher = more important)
        """
        if self.status in [OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]:
            self.priority = new_priority

    def is_ready_for_processing(self, now: datetime | None = None) -> bool:
        """Check if message is ready to be processed now.

        Args:
            now: Reference time for the lock/retry comparisons. Defaults to the
                active domain's clock.

        Returns:
            True if message can be processed immediately
        """
        now = _domain_now(now)

        if self.status not in [OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]:
            return False

        if self._is_locked(now) or not self._can_retry():
            return False

        # Ready unless a retry time is set and still in the future.
        return not (self.next_retry_at and now < ensure_utc_aware(self.next_retry_at))

    # Private helper methods
    def _is_locked(self, now: datetime | None = None) -> bool:
        """Check if message is currently locked for processing.

        Args:
            now: Reference time for the lock-window comparison. Defaults to the
                active domain's clock.
        """
        now = _domain_now(now)
        return bool(
            self.locked_until
            and now < ensure_utc_aware(self.locked_until)
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
        self,
        base_delay_seconds: int = 60,
        max_backoff_seconds: int = 3600,
        now: datetime | None = None,
    ) -> None:
        """Calculate next retry time using exponential backoff.
        Args:
            base_delay_seconds: Base delay in seconds for the backoff calculation.
            max_backoff_seconds: Maximum allowable delay in seconds to cap the backoff.
            now: Reference time the backoff is measured from. Defaults to the
                active domain's clock.
        """
        now = _domain_now(now)
        delay = min(base_delay_seconds * (2**self.retry_count), max_backoff_seconds)
        self.next_retry_at = now + timedelta(seconds=delay)


# Recommended indexes for the outbox table. Applied when the framework
# registers a per-provider Outbox (see ``DomainInfrastructure.initialize_outbox``).
#
# - The active-set partial index keeps the polling index tiny: only pending and
#   failed rows are indexed, not the published archive (which dominates volume).
#   Its columns follow the claim order (``_CLAIM_ORDER``): priority descending,
#   then commit order.
# - ``(message_id, target_broker)`` is unique for idempotency / find-by-message-id.
#   A single event is dual-written to the outbox once per target broker (the
#   internal broker plus every external broker), all rows sharing one
#   ``message_id`` and differing only by ``target_broker``, so ``message_id``
#   alone cannot be unique. The framework always writes a non-NULL
#   ``target_broker`` (see ``UnitOfWork``), which this composite uniqueness
#   depends on: a NULL is treated as distinct on PostgreSQL/SQLite and would
#   defeat idempotency. In single-broker mode the index still enforces one row
#   per ``message_id`` (under the internal broker name).
# - ``correlation_id`` supports trace-oriented lookups.
# - ``(target_broker, stream_category, partition_key, status)`` backs the
#   claim's hold-back check, which looks for earlier rows of the same group
#   that are not yet published.
OUTBOX_INDEXES = [
    Index(
        "status",
        "priority",
        "created_at",
        "sequence_number",
        desc=("priority",),
        where=Q(status__in=[OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]),
        name="ix_outbox_active",
    ),
    Index("message_id", "target_broker", unique=True),
    Index("correlation_id"),
    Index(
        "target_broker",
        "stream_category",
        "partition_key",
        "status",
        name="ix_outbox_hold_back",
    ),
]

# The order rows are claimed in: higher priority first, then commit order
# (``created_at``, with ``sequence_number`` breaking ties within one commit).
# ``id`` says nothing about commit order; it only keeps the order the same on
# every run when the other keys tie. Shared by ``find_unprocessed`` and
# ``claim_batch`` so the two cannot drift.
_CLAIM_ORDER = ["-priority", "created_at", "sequence_number", "id"]

# Commit order without the priority key: the order a group's rows must publish
# in. Matches the tail of ``_CLAIM_ORDER``.
_COMMIT_ORDER = ("created_at", "sequence_number", "id")


@dataclass(frozen=True)
class OutboxLanes:
    """The priority-lane split as the outbox sees it.

    A row is in the backfill lane when lanes are enabled, it targets the
    internal broker, and its priority is below the threshold. Every other row
    is in the primary lane. Rows for an external broker are always primary,
    because lanes apply only to the internal processor. The claim's hold-back
    and :meth:`OutboxProcessor.process_batch` both use this, so they agree on
    which rows share a group.
    """

    enabled: bool
    threshold: int
    internal_broker: str

    @classmethod
    def from_config(cls, config: Any) -> "OutboxLanes":
        """Read the lane split from domain config."""
        lanes_config = config.get("server", {}).get("priority_lanes", {})
        return cls(
            enabled=bool(lanes_config.get("enabled", False)),
            threshold=lanes_config.get("threshold", 0),
            internal_broker=config.get("outbox", {}).get(
                "broker", DEFAULT_TARGET_BROKER
            ),
        )

    def is_backfill(self, target_broker: str, priority: int) -> bool:
        """Whether a row with these values publishes to the backfill lane."""
        return (
            self.enabled
            and target_broker == self.internal_broker
            and priority < self.threshold
        )

    def group_key(self, row: "Outbox") -> tuple[str, str, str, bool] | None:
        """The row's hold-back group, or ``None`` when it has none.

        The group is ``(target_broker, stream_category, partition_key,
        backfill)``, which is the stream the row publishes to. A row without
        both a ``partition_key`` and a ``stream_category`` has no group.
        """
        if row.partition_key is None or row.stream_category is None:
            return None
        return (
            row.target_broker,
            row.stream_category,
            row.partition_key,
            self.is_backfill(row.target_broker, row.priority),
        )

    def lane_index(self, row: "Outbox") -> int | None:
        """The row's entry in :meth:`hold_back`'s lanes (primary ``0``,
        backfill ``1``), or ``None`` when it has no group."""
        group = self.group_key(row)
        return None if group is None else int(group[3])

    def hold_back(self) -> HoldBack:
        """The :class:`~protean.port.dao.HoldBack` that ``claim_batch``
        passes to the DAO."""
        lanes: tuple[Q, ...] = ()
        if self.enabled:
            backfill = Q(target_broker=self.internal_broker) & Q(
                priority__lt=self.threshold
            )
            primary = ~Q(target_broker=self.internal_broker) | Q(
                priority__gte=self.threshold
            )
            lanes = (primary, backfill)
        return HoldBack(
            group_by=("target_broker", "stream_category", "partition_key"),
            applies=Q(partition_key__isnull=False) & Q(stream_category__isnull=False),
            # Every status but PUBLISHED holds the group. An ABANDONED row
            # halts its key until an operator deals with it.
            holds=Q(
                status__in=[
                    OutboxStatus.PENDING.value,
                    OutboxStatus.PROCESSING.value,
                    OutboxStatus.FAILED.value,
                    OutboxStatus.ABANDONED.value,
                ]
            ),
            order=_COMMIT_ORDER,
            lane_of=self.lane_index,
            lanes=lanes,
        )


def commit_order_key(row: "Outbox") -> tuple[Any, ...]:
    """Python sort key for commit order, with NULL ``sequence_number`` last,
    the same as the claim order.

    ``id`` is left out: the store compares it by its column type (a number
    under ``identity_type="integer"``), which ``str`` would not match. A
    stable sort keeps the claim's own order when the other keys tie.
    """
    return (
        ensure_utc_aware(row.created_at),
        row.sequence_number is None,
        row.sequence_number or 0,
    )


class OutboxRepository(BaseRepository):
    """Repository for querying outbox messages with specialized filtering methods."""

    def _apply_limit_and_execute(
        self, query: "QuerySet", limit: int | None
    ) -> list[Outbox]:
        """Helper method to apply limit and handle zero limit case."""
        if limit is not None and limit == 0:
            return []

        if limit is not None and limit > 0:
            query = query.limit(limit)

        # The poll path only needs the rows, never the full match count, so
        # skip the adapter's total-count round-trip (a wrapped ``COUNT`` on SQL).
        return cast(list[Outbox], query.all(with_total=False).items)

    def _eligibility_criteria(
        self, now: datetime, target_broker: str | None = None
    ) -> Q:
        """Return the ``Q`` that selects the messages :meth:`claim_batch` treats as ready.

        When *target_broker* is given, only rows for that broker match.
        """
        criteria = Q(
            status__in=[
                OutboxStatus.PENDING.value,
                OutboxStatus.FAILED.value,
                OutboxStatus.PROCESSING.value,
            ]
        )
        # ``__lte``, not ``__lt``: a lock is free at the exact ``locked_until``
        # instant, matching ``Outbox._is_locked`` (``now < locked_until`` means
        # locked, so equality is reclaimable) and the ``next_retry_at`` boundary
        # below. Using ``__lt`` here made the claim path disagree with the
        # aggregate at that one instant.
        criteria &= Q(locked_until__isnull=True) | Q(locked_until__lte=now)
        criteria &= Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)
        criteria &= Q(retry_count__lt=F("max_retries"))
        if target_broker is not None:
            criteria &= Q(target_broker=target_broker)
        return criteria

    def find_unprocessed(
        self,
        limit: int | None = None,
        target_broker: str | None = None,
    ) -> list[Outbox]:
        """Return messages that are ready for processing, without claiming them.

        Readiness and order are the same as for :meth:`claim_batch`. The rows are
        not locked, so use this to inspect the queue and :meth:`claim_batch` to
        process it. The claim's hold-back is not applied, so the list can include a
        partitioned row that :meth:`claim_batch` will not return yet.

        Args:
            limit: Maximum number of messages to return. ``0`` returns none.
            target_broker: When given, only return rows for this broker.
        """
        # Handle zero limit case
        if limit is not None and limit == 0:
            return []

        now = self._dao.domain.clock.now()
        query = self._dao.query.filter(self._eligibility_criteria(now, target_broker))

        # Same order as ``claim_batch``: priority (higher first), then commit order
        query = query.order_by(_CLAIM_ORDER)

        return self._apply_limit_and_execute(query, limit)

    def claim_batch(
        self,
        worker_id: str,
        limit: int,
        target_broker: str | None = None,
        lock_duration_minutes: int = DEFAULT_LOCK_DURATION_MINUTES,
        lanes: OutboxLanes | None = None,
    ) -> list[Outbox]:
        """Claim up to *limit* ready messages for *worker_id* and return them.

        Each claimed row is set to ``PROCESSING`` and locked by *worker_id* for
        *lock_duration_minutes*. The claim follows the
        :meth:`~protean.port.dao.BaseDAO._claim` contract.

        A message is ready when:

        - its status is ``PENDING``, ``FAILED`` or ``PROCESSING``;
        - its lock is free (``locked_until`` is null or has passed), so a
          ``PROCESSING`` row is ready only after its worker's lock expired;
        - its ``next_retry_at`` is null or has passed;
        - its ``retry_count`` is below ``max_retries``;
        - its ``target_broker`` matches *target_broker*, when given.

        A row with both a ``partition_key`` and a ``stream_category`` is held back
        while an earlier row of its group is unpublished and not claimed in the
        same call (ADR-0028). The group is ``(target_broker, stream_category,
        partition_key, lane)``. The lane comes from *lanes*, or from
        ``[server.priority_lanes]`` when *lanes* is ``None``. So a failed,
        abandoned or in-flight row stops the later rows of its key, and other keys
        keep flowing.

        Args:
            limit: ``<= 0`` claims nothing.

        Returns:
            The claimed messages, highest ``priority`` first, then in commit order
            (``created_at``, then ``sequence_number``).
        """
        if limit <= 0:
            return []

        now = self._dao.domain.clock.now()
        if lanes is None:
            lanes = OutboxLanes.from_config(self._dao.domain.config)
        hold_back = lanes.hold_back()

        claimed = cast(
            list[Outbox],
            self._dao._claim(
                criteria=self._eligibility_criteria(now, target_broker),
                claim_fields={
                    "status": OutboxStatus.PROCESSING.value,
                    "locked_by": worker_id,
                    "locked_until": now + timedelta(minutes=lock_duration_minutes),
                    "last_processed_at": now,
                },
                limit=limit,
                order_by=_CLAIM_ORDER,
                hold_back=hold_back,
            ),
        )

        # Trace-validation seam (inactive by default): each claimed row is now
        # PROCESSING under this worker's lock — the spec's Claim transition. Guarded
        # so the poll loop does no per-row work unless a capture is running.
        if outbox_trace.is_active():
            for row in claimed:
                outbox_trace.record(
                    action="claim", worker=worker_id, message=str(row.id)
                )

        return claimed

    def find_failed(self, limit: int | None = PAGE_SIZE) -> list[Outbox]:
        """Find messages that have failed processing.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages in FAILED status
        """
        query = self._dao.query.filter(status=OutboxStatus.FAILED.value)
        query = query.order_by("-last_processed_at")

        return self._apply_limit_and_execute(query, limit)

    def find_abandoned(self, limit: int | None = PAGE_SIZE) -> list[Outbox]:
        """Find messages that have been abandoned.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages in ABANDONED status
        """
        query = self._dao.query.filter(status=OutboxStatus.ABANDONED.value)
        query = query.order_by("-last_processed_at")

        return self._apply_limit_and_execute(query, limit)

    def find_published(self, limit: int | None = PAGE_SIZE) -> list[Outbox]:
        """Find messages that have been successfully published.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages in PUBLISHED status
        """
        query = self._dao.query.filter(status=OutboxStatus.PUBLISHED.value)
        query = query.order_by("-published_at")

        return self._apply_limit_and_execute(query, limit)

    def find_processing(self, limit: int | None = PAGE_SIZE) -> list[Outbox]:
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
        self, stream_name: str, limit: int | None = PAGE_SIZE
    ) -> list[Outbox]:
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

    def find_by_message_id(
        self, message_id: str, target_broker: str | None = None
    ) -> Outbox | None:
        """Find a single outbox message by its message ID.

        In multi-broker mode a published event is dual-written once per target
        broker, so ``message_id`` is not unique on its own. Pass
        ``target_broker`` to select the unique ``(message_id, target_broker)``
        row. Without it the first matching row is returned; use
        :meth:`find_all_by_message_id` to retrieve every per-broker row.

        Args:
            message_id: The message ID to look up
            target_broker: When given, restrict the lookup to this broker's row

        Returns:
            The matching Outbox message, or None if not found
        """
        criteria = {"message_id": message_id}
        if target_broker is not None:
            criteria["target_broker"] = target_broker
        results = cast(list[Outbox], self._dao.query.filter(**criteria).all().items)
        return results[0] if results else None

    def find_all_by_message_id(self, message_id: str) -> list[Outbox]:
        """Find every outbox row sharing a message ID.

        A published event is dual-written once per target broker, so a single
        ``message_id`` can map to several rows, one per ``target_broker``.

        Args:
            message_id: The message ID to look up

        Returns:
            All Outbox messages with the given message ID (possibly empty)
        """
        return cast(
            list[Outbox], self._dao.query.filter(message_id=message_id).all().items
        )

    def find_by_message_type(
        self, message_type: str, limit: int | None = PAGE_SIZE
    ) -> list[Outbox]:
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
        self, min_priority: int = 1, limit: int | None = PAGE_SIZE
    ) -> list[Outbox]:
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
        self, correlation_id: str, limit: int | None = PAGE_SIZE
    ) -> list[Outbox]:
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
        self, causation_id: str, limit: int | None = PAGE_SIZE
    ) -> list[Outbox]:
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

    def find_stale_processing(self, stale_threshold_minutes: int = 10) -> list[Outbox]:
        """Find messages that have been processing for too long (stale locks).

        Args:
            stale_threshold_minutes: Minutes after which a processing message is considered stale

        Returns:
            List of Outbox messages that are stale
        """
        threshold_time = self._dao.domain.clock.now() - timedelta(
            minutes=stale_threshold_minutes
        )

        query = self._dao.query.filter(
            status=OutboxStatus.PROCESSING.value, last_processed_at__lt=threshold_time
        )
        query = query.order_by("last_processed_at")

        return cast(list[Outbox], query.all().items)

    def find_recent(
        self, hours: int = 24, limit: int | None = PAGE_SIZE
    ) -> list[Outbox]:
        """Find messages created within the specified number of hours.

        Args:
            hours: Number of hours to look back
            limit: Maximum number of messages to return

        Returns:
            List of recent Outbox messages
        """
        threshold_time = self._dao.domain.clock.now() - timedelta(hours=hours)

        query = self._dao.query.filter(created_at__gte=threshold_time)
        query = query.order_by("-created_at")

        return self._apply_limit_and_execute(query, limit)

    def find_retry_ready(self, limit: int | None = PAGE_SIZE) -> list[Outbox]:
        """Find failed messages that are ready for retry.

        Args:
            limit: Maximum number of messages to return

        Returns:
            List of Outbox messages ready for retry
        """
        current_time = self._dao.domain.clock.now()

        query = self._dao.query.filter(
            status=OutboxStatus.FAILED.value, next_retry_at__lte=current_time
        ).order_by("-priority")

        return self._apply_limit_and_execute(query, limit)

    def count_by_status(self, target_broker: str | None = None) -> dict[str, int]:
        """Get count of messages by their status.

        Args:
            target_broker: Count only rows bound for this broker. Mirrors the
                filter ``OutboxProcessor`` applies when
                ``outbox.external_brokers`` is set, so a caller reporting
                per-processor counts sees that processor's own backlog. ``None``
                means do not filter, which is what a single processor wants: it
                owns every row, and matching on the column would skip legacy
                rows holding NULL, since ``_coerce_target_broker`` runs on read
                in Python and not in the query.

        Returns:
            Dictionary with status as key and count as value
        """
        return {
            status.value: (
                self._dao.query.filter(
                    status=status.value, target_broker=target_broker
                ).count()
                if target_broker is not None
                else self._dao.query.filter(status=status.value).count()
            )
            for status in OutboxStatus
        }

    def _cleanup_batch_size(self) -> int:
        """Resolve the cleanup batch size from ``[outbox.cleanup]`` config.

        Reads from the repository's own domain (not the ``current_domain``
        global) so cleanup works in standalone/cron usage with no active domain
        context. Defaults to 5000 when unset, matching ``domain.config``.
        """
        return cast(
            int,
            self._dao.domain.config.get("outbox", {})
            .get("cleanup", {})
            .get("batch_size", 5000),
        )

    def cleanup_old_published(
        self, older_than_hours: int = 168, batch_size: int | None = None
    ) -> int:
        """Clean up published messages older than specified hours.

        Args:
            older_than_hours: Age in hours after which published messages should be cleaned up
            batch_size: Rows to delete per batch. Defaults to the
                ``[outbox.cleanup]`` config value (5000).

        Returns:
            Number of messages deleted
        """
        threshold_time = self._dao.domain.clock.now() - timedelta(
            hours=older_than_hours
        )

        return self._delete_in_batches(
            Q(status=OutboxStatus.PUBLISHED.value, published_at__lt=threshold_time),
            batch_size if batch_size is not None else self._cleanup_batch_size(),
        )

    def cleanup_old_abandoned(
        self, older_than_hours: int = 720, batch_size: int | None = None
    ) -> int:
        """Delete abandoned messages older than *older_than_hours* and return the count.

        Age is measured from ``last_processed_at``. Abandoned rows with a
        ``partition_key`` are kept whatever their age.

        Args:
            batch_size: Rows to delete per batch. Defaults to
                ``outbox.cleanup.batch_size`` (5000).
        """
        threshold_time = self._dao.domain.clock.now() - timedelta(
            hours=older_than_hours
        )

        return self._delete_in_batches(
            Q(
                status=OutboxStatus.ABANDONED.value,
                last_processed_at__lt=threshold_time,
                # A keyed abandoned row holds back the later rows of its key.
                # Deleting it would let the key move on with a gap.
                partition_key__isnull=True,
            ),
            batch_size if batch_size is not None else self._cleanup_batch_size(),
        )

    def cleanup_old_messages(
        self,
        published_retention_hours: int = 168,
        abandoned_retention_hours: int = 720,
        batch_size: int | None = None,
    ) -> dict[str, int]:
        """Delete old published and abandoned messages.

        Each status is cleaned as :meth:`cleanup_old_published` and
        :meth:`cleanup_old_abandoned` do, with its own retention.

        Args:
            batch_size: Rows to delete per batch. Defaults to
                ``outbox.cleanup.batch_size`` (5000).

        Returns:
            The deleted counts under ``"published"``, ``"abandoned"`` and
            ``"total"``.
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


def backfill_suffix_from_config(config: Any) -> str:
    """Return the configured ``[server.priority_lanes].backfill_suffix``.

    A partition key must not equal this suffix (ADR-0028 decision 3). The unit
    of work and outbox reconciliation both validate keys against it, so both
    read it through this helper and share one default.
    """
    suffix: str = (
        config.get("server", {})
        .get("priority_lanes", {})
        .get("backfill_suffix", "backfill")
    )
    return suffix


def _outbox_provider_names(domain: Any) -> list[str]:
    """Return the database providers that get outbox processors, in ``domain.providers`` order.

    A provider qualifies when it is managed and a concrete aggregate names it in
    its ``provider`` option. Event-sourced aggregates count. Abstract aggregates
    and the framework's internal elements do not.
    """
    # The unit of work writes outbox rows only to the providers of the
    # aggregates it persists, so a provider no aggregate names would get a
    # processor that polls an empty table. An abstract aggregate is skipped
    # because a concrete subclass does not inherit its ``provider``.
    used = {
        record.cls.meta_.provider
        for record in domain.registry.aggregates.values()
        if not getattr(record.cls.meta_, "abstract", False)
    }
    return [
        name
        for name, provider in domain.providers.items()
        if getattr(provider, "managed", True) and name in used
    ]


def _is_outboxed_event(domain: Any, message: Any, provider_name: str) -> bool:
    """Whether the unit of work writes a row for *message* in *provider_name*'s outbox.

    See ``_resolve_outboxed_event_class`` for the rules.
    """
    return _resolve_outboxed_event_class(domain, message, provider_name) is not None


def _resolve_outboxed_event_class(
    domain: Any, message: Any, provider_name: str
) -> "type[BaseEvent] | None":
    """Return the event class the unit of work writes outbox rows for *message* as, or ``None``.

    ``None`` means the unit of work writes no row for *message* in
    *provider_name*'s outbox. A message qualifies when its type string resolves
    in this domain's registry to an event that is ``part_of`` an aggregate on
    *provider_name*. An older event version resolves through the upcaster chain
    to the current class.

    Messages that do not qualify include another domain's events in a shared
    store, foreign types mapped with ``register_external_event``, commands,
    process manager transition events, and events of aggregates on another
    provider.
    """
    headers = message.metadata.headers if message.metadata else None
    type_string = headers.type if headers else None
    if not type_string:
        return None

    # Type strings start with the domain name in CamelCase, so domains whose
    # names give the same CamelCase form (``my-domain``, ``my_domain``) cannot
    # be told apart here.
    element_cls = domain._events_and_commands.get(type_string)
    # ``register_external_event`` can map a foreign type string onto a class
    # this domain also registers. The unit of work only writes the class's own
    # current type, so a direct match must equal it.
    if element_cls is not None and element_cls.__type__ != type_string:
        return None
    if element_cls is None:
        element_cls = domain._upcaster_chain.resolve_event_class(type_string)
    if element_cls is None or element_cls.element_type != DomainObjects.EVENT:
        return None

    # ``register_external_event`` maps a foreign type string to the foreign
    # class, which keeps its ``part_of``. Only events in this domain's own
    # registry are raised here.
    record = domain._domain_registry._elements[DomainObjects.EVENT.value].get(
        fqn(element_cls)
    )
    if record is None or record.cls is not element_cls:
        return None

    part_of = getattr(element_cls.meta_, "part_of", None)
    if part_of is None or part_of.element_type != DomainObjects.AGGREGATE:
        return None
    if part_of.meta_.provider != provider_name:
        return None
    return cast("type[BaseEvent]", element_cls)


def _rebuilt_partition_key(
    message: Any, partition_keys: dict[str, str], backfill_suffix: str
) -> str | None:
    """The ``partition_key`` the unit of work would have set for *message*.

    Categories without a ``sequential_by`` handler have no key, so the event is
    only rebuilt for a partitioned category. Raises ``DeserializationError`` or
    ``ValidationError`` if the stored event no longer loads or its key no longer
    validates (the payload schema, ``sequential_by`` or ``backfill_suffix``
    changed after it was written).
    """
    from protean.core.unit_of_work import UnitOfWork  # noqa: PLC0415 - circular

    domain_meta = message.metadata.domain
    category = getattr(domain_meta, "stream_category", None)
    if not category or category not in partition_keys:
        return None

    return UnitOfWork._extract_partition_key(
        message.to_domain_object(), partition_keys, backfill_suffix
    )


def _cleanup_cutoff(domain: Any, outbox_config: dict[str, Any]) -> datetime:
    """The oldest event time whose outbox rows cleanup cannot have deleted yet.

    Uses the shorter of ``outbox.cleanup.published_retention_hours`` and
    ``outbox.cleanup.abandoned_retention_hours``, with the same defaults the
    outbox processor uses.
    """
    cleanup_config = outbox_config.get("cleanup", {})
    retention_hours = min(
        cleanup_config.get("published_retention_hours", 168),
        cleanup_config.get("abandoned_retention_hours", 720),
    )
    now: datetime = domain.clock.now()
    return now - timedelta(hours=retention_hours)


def _written_after(message: Any, cutoff: datetime) -> bool:
    """Whether *message* was written at or after *cutoff*.

    A message with no stored time does not count. Its age is unknown, so
    cleanup may already have deleted its row.
    """
    headers = message.metadata.headers if message.metadata else None
    written_at = headers.time if headers else None
    if written_at is None:
        return False
    return ensure_utc_aware(written_at) >= cutoff


def reconcile_outbox(
    domain: Any, provider_name: str = "default", limit: int = 1000
) -> int:
    """Create outbox rows for events that are in the event store but have no
    outbox row, and return how many rows were created.

    The function scans the most recent ``limit`` messages of ``$all``. It finds
    the newest event this domain's outbox covers, and repairs only when that
    event is missing its row. ``limit`` counts every message in ``$all``,
    including ones the function skips. Returns ``0`` when the domain has no
    outbox.

    Only events raised by this domain's aggregates on ``provider_name`` are
    repaired. Another domain's events in a shared store, commands, process
    manager transition events, events of aggregates on other providers, and
    foreign types mapped with ``register_external_event`` are skipped.

    A rebuilt row carries the ``partition_key`` the unit of work would have set,
    and the default ``priority``. If the key can no longer be computed, the row
    is saved as abandoned and an error is logged.

    A ``published`` event also gets a row for each broker in
    ``outbox.external_brokers`` that it lacks. A message whose internal row
    exists is left alone, so a broker added to ``external_brokers`` later is not
    back-filled.

    Events older than the shorter of ``outbox.cleanup.published_retention_hours``
    and ``outbox.cleanup.abandoned_retention_hours`` are skipped, and so are
    events with no stored time.

    The return value counts rows created, internal and external.
    """
    if not getattr(domain, "has_outbox", False):
        return 0

    # Enter the passed domain's context so the event store, repositories, and
    # the UnitOfWork below all resolve against THIS domain regardless of what
    # the caller has active. domain_context is re-entrant, so this is safe when
    # the caller (the CLI, the engine startup sweep) is already inside it.
    with domain.domain_context():
        return _reconcile_outbox(domain, provider_name, limit)


def _reconcile_outbox(domain: Any, provider_name: str, limit: int) -> int:
    from protean.core.unit_of_work import UnitOfWork  # noqa: PLC0415 - circular

    store = domain.event_store.store
    last = store.read_last_message("$all")
    if last is None:
        return 0

    outbox_config = domain.config.get("outbox", {})
    internal_broker = outbox_config.get("broker", DEFAULT_TARGET_BROKER)
    external_brokers: list[str] = outbox_config.get("external_brokers", [])
    outbox_repo = domain._get_outbox_repo(provider_name)

    def _existing_brokers(message_id: str) -> set[str]:
        return {
            row.target_broker for row in outbox_repo.find_all_by_message_id(message_id)
        }

    def _internal_row_exists(message_id: str) -> bool:
        return internal_broker in _existing_brokers(message_id)

    # Fast path: if the newest message is one of this domain's outboxed events
    # and already has its internal row, the last unit of work committed fully
    # and there is nothing at the tail to repair. This keeps the startup sweep
    # cheap in the common (no-crash) case. The gap this repairs is the crash
    # window between the event store append and the outbox commit (ADR-0015),
    # so it is always at the tail.
    if _is_outboxed_event(domain, last, provider_name) and _internal_row_exists(
        last.metadata.headers.id
    ):
        return 0

    tail = last.metadata.event_store.global_position
    start = max(0, tail - limit + 1)
    messages = store.read("$all", position=start, no_of_messages=limit)

    # Walk back from the tail to the newest message this domain outboxes. The
    # newest message overall may be foreign, a command, or a transition event.
    # None of those ever get a row, so a missing row for one of them does not
    # mean the last commit crashed.
    # Cleanup deletes delivered rows and abandoned rows without a partition key
    # once they pass their retention, and a deleted row looks the same as one
    # lost in a crash. An event is never older than its row's ``published_at`` or
    # ``last_processed_at``, so skipping events older than the shorter
    # retention skips every row cleanup could have deleted.
    cutoff = _cleanup_cutoff(domain, outbox_config)
    qualifying = [
        m
        for m in messages
        if _is_outboxed_event(domain, m, provider_name) and _written_after(m, cutoff)
    ]
    if not qualifying or _internal_row_exists(qualifying[-1].metadata.headers.id):
        return 0

    existing_brokers = {
        m.metadata.headers.id: _existing_brokers(m.metadata.headers.id)
        for m in qualifying
    }
    missing = [
        m
        for m in qualifying
        if internal_broker not in existing_brokers[m.metadata.headers.id]
    ]
    # Only a missing internal row marks a lost commit: the unit of work saves
    # all of a message's rows in one commit.
    if not missing:  # pragma: no cover - race guard: a concurrent sweep can
        # insert the rows between the check above and this query.
        return 0

    partition_keys = domain._partition_keys
    backfill_suffix = backfill_suffix_from_config(domain.config)

    created = 0
    with UnitOfWork():
        # The rebuilt rows form one commit, so number them in event store
        # order the way the Unit of Work numbers the events of a commit.
        for sequence_number, message in enumerate(missing):
            message_id = message.metadata.headers.id
            domain_meta = message.metadata.domain
            abandon_reason = None
            try:
                partition_key = _rebuilt_partition_key(
                    message, partition_keys, backfill_suffix
                )
            except (DeserializationError, ValidationError) as exc:
                # A row without its key would be published to the base
                # category, where no partitioned handler reads it.
                partition_key = None
                abandon_reason = f"partition_key could not be computed: {exc}"
                logger.error(
                    "outbox.reconcile: saving the row(s) for message %s as "
                    "abandoned, because its %s",
                    message_id,
                    abandon_reason,
                )

            # The unit of work writes one row per external broker for a
            # ``published`` event, all in the same commit as the internal row.
            # Neither the ``published`` flag nor ``external_brokers`` is stored
            # with the event, so both come from the current settings.
            target_brokers = [internal_broker]
            event_cls = _resolve_outboxed_event_class(domain, message, provider_name)
            if (
                external_brokers
                and event_cls is not None
                and getattr(event_cls.meta_, "published", False)
            ):
                target_brokers.extend(
                    broker
                    for broker in external_brokers
                    if broker not in existing_brokers[message_id]
                )

            for target_broker in target_brokers:
                # ``priority`` is left at its default: the original request's
                # priority is not stored with the event.
                outbox_message = Outbox.create_message(
                    message_id=message_id,
                    stream_name=message.metadata.headers.stream,
                    message_type=message.metadata.headers.type,
                    data=message.data,
                    metadata=message.metadata,
                    correlation_id=getattr(domain_meta, "correlation_id", None),
                    causation_id=getattr(domain_meta, "causation_id", None),
                    sequence_number=sequence_number,
                    target_broker=target_broker,
                    partition_key=partition_key,
                    stream_category=getattr(domain_meta, "stream_category", None),
                )
                if abandon_reason is not None:
                    outbox_message.mark_abandoned(
                        abandon_reason, cause="Invalid partition key"
                    )
                outbox_repo._dao.save(outbox_message)
                created += 1

    return created
