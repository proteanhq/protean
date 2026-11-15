"""The `EventStore` service.

An event-store adapter implements `EventStorePort`: it writes rows and reads
them by stream, category or the whole store. `EventStore` wraps the domain's
one adapter and builds the features on top of it: appending a domain object,
reading messages with snapshot rows left out, paging a whole stream, loading an
aggregate at its latest version or at a point in history, writing snapshots,
tracing causation and checking the store's integrity.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    ObjectNotFoundError,
    ValidationError,
)
from protean.infra import causation, integrity
from protean.infra.registry import event_stores as event_store_registry
from protean.integrations.logging import SNAPSHOT_EVENT_DISCARDED, log_snapshot_event
from protean.ir.diagnostics import DiagnosticCode
from protean.port.event_store import (
    SNAPSHOT_TYPE,
    EventStoreCapabilities,
    EventStoreHealth,
    EventStorePort,
    RawMessage,
)
from protean.utils.eventing import Message
from protean.utils.telemetry import set_span_error

if TYPE_CHECKING:
    from protean.core.aggregate import BaseAggregate
    from protean.core.command import BaseCommand
    from protean.core.event import BaseEvent
    from protean.domain import Domain
    from protean.infra.causation import CausationNode
    from protean.infra.integrity import IntegrityReport
    from protean.port.event_store import BaseEventStore

logger = logging.getLogger(__name__)

# Window size for the backward scan that skips a trailing snapshot in
# ``read_last_message`` (see ``_last_non_snapshot_message``). One window is one
# ``_read_raw`` of at most this many rows near the tail. Matches the default read
# page size so the common case (a single snapshot as the last row) resolves in
# one small read.
_SNAPSHOT_TAIL_WINDOW = 1000


def _is_snapshot_row(raw_message: Mapping[str, Any]) -> bool:
    """Whether a raw store row is a snapshot rather than an event/command.

    Keys strictly on ``type == "SNAPSHOT"``: a row with genuinely missing or
    ``None`` metadata that is *not* a snapshot still flows to
    ``Message.deserialize`` and raises, so real corruption is not swallowed.
    """
    return raw_message.get("type") == SNAPSHOT_TYPE


def _next_cursor(raw_message: Mapping[str, Any], by_global_position: bool) -> int:
    """The ``position`` to resume a paged read after ``raw_message``.

    Reads are inclusive, so resume one past the last raw row seen. The row's
    top-level position is read directly (never through ``Message.deserialize``,
    which would raise on a snapshot's ``None`` metadata). A persisted row
    always carries the relevant position; a missing one is a corrupt row that
    would otherwise loop or truncate the read silently, so raise.
    """
    key = "global_position" if by_global_position else "position"
    last: int | None = raw_message.get(key)
    if last is None:
        raise IncorrectUsageError(
            "Cannot page the event store: a message is missing its position."
        )
    return last + 1


def _parse_event_time(raw_time: Any) -> datetime | None:
    """Normalise a raw ``time`` value from an event message to ``datetime``.

    Accepts a ``datetime`` (a ``RawMessage`` row) or an ISO-8601 string
    (a serialized message or header).
    """
    if raw_time is None:
        return None
    if isinstance(raw_time, datetime):
        return raw_time
    if isinstance(raw_time, str):
        return datetime.fromisoformat(raw_time)
    return None


def _make_comparable(
    event_time: datetime, cutoff: datetime
) -> tuple[datetime, datetime]:
    """Ensure both datetimes are comparable (both naive or both aware).

    MessageDB (PostgreSQL) returns timezone-naive timestamps stored as UTC,
    while the memory adapter stores ``datetime.now(UTC)`` which is
    timezone-aware.  When they differ, strip tzinfo from both sides so the
    comparison proceeds. All event store timestamps are treated as UTC.
    """
    event_aware = event_time.tzinfo is not None
    cutoff_aware = cutoff.tzinfo is not None

    if event_aware == cutoff_aware:
        return event_time, cutoff

    # Mixed: strip tzinfo from both (both are in UTC by convention)
    return event_time.replace(tzinfo=None), cutoff.replace(tzinfo=None)


def _is_fact_stream_identifier(identifier: str) -> bool:
    """Whether a parsed identifier belongs to a fact-event stream.

    Fact streams are named ``{category}-fact-{identifier}``, so their parsed
    identifier segment starts with ``fact-``. They hold ``...FactEvent``
    records, not an aggregate instance's events. This is only consulted for
    aggregates with ``fact_events=True`` (see
    [`create_snapshots`][protean.infra.event_store.EventStore.create_snapshots]),
    so an ordinary instance whose identifier starts with ``fact-`` is unaffected
    unless its own aggregate also emits fact events.
    """
    return identifier.startswith("fact-")


def _log_snapshot_discarded(
    part_of: type[BaseAggregate], identifier: str, error: ValidationError
) -> None:
    """Emit a WARNING that a snapshot was discarded as stale.

    Called from both load paths when a stored snapshot no longer
    constructs against the current aggregate schema. The aggregate still
    loads by replaying the event stream; the warning marks snapshots that
    need rebuilding (``protean snapshot create``).
    """
    log_snapshot_event(
        SNAPSHOT_EVENT_DISCARDED,
        aggregate=part_of.__name__,
        aggregate_id=identifier,
        reason=str(error),
    )


def _aggregate_from_snapshot(
    service: EventStore,
    part_of: type[BaseAggregate],
    identifier: str,
    stream: str,
    at_version: int,
) -> BaseAggregate | None:
    """Return the aggregate built from its latest snapshot and the events
    after it, up to ``at_version``.

    Returns ``None`` when there is no snapshot, the snapshot is past
    ``at_version``, or the snapshot no longer constructs.
    """
    snapshot_message = service._require_adapter().get_last_stream_message(
        f"{part_of.meta_.stream_category}:snapshot-{identifier}"
    )
    if not snapshot_message:
        return None

    snapshot_data = snapshot_message["data"] or {}
    snapshot_version: int = snapshot_data.get("_version", -1)
    if snapshot_version > at_version:
        return None

    try:
        # Snapshot is usable: initialize from it
        aggregate = part_of(**snapshot_data)
    except ValidationError as exc:
        # Stale snapshot (predates the current schema). Discard it,
        # log a warning, and let the caller rebuild from the
        # authoritative event stream.
        _log_snapshot_discarded(part_of, identifier, exc)
        return None

    remaining = at_version - aggregate._version
    if remaining > 0:
        event_stream = service._read_stream_fully(
            stream,
            start_position=aggregate._version + 1,
            max_rows=remaining,
        )
        for event_message in event_stream:
            event = Message.deserialize(event_message).to_domain_object()
            aggregate._apply(event)
    # else: snapshot is exactly at the requested version
    return aggregate


def _aggregate_from_events(
    service: EventStore,
    part_of: type[BaseAggregate],
    stream: str,
    at_version: int,
) -> BaseAggregate | None:
    """Return the aggregate replayed from the first ``at_version + 1`` events
    of ``stream``, or ``None`` when the stream is empty."""
    event_stream = service._read_stream_fully(stream, max_rows=at_version + 1)

    if not event_stream:
        return None

    events = [Message.deserialize(msg).to_domain_object() for msg in event_stream]
    return part_of.from_events(events)


class EventStore:
    """The framework's view of the domain's event-store adapter.

    `domain.event_store` returns one. The adapter is built by `domain.init()`;
    until then `_adapter` is `None`.

    Raises:
        ConfigurationError: From every feature method and forwarder that reaches
            the adapter, when `domain.init()` has not built it yet. The error
            carries the code `CONFIG_EVENT_STORE_NOT_INITIALIZED`. `store`,
            `close` and the static `category` need no adapter and do not
            raise `ConfigurationError`.
    """

    def __init__(self, domain: Domain) -> None:
        self.domain: Domain = domain
        self._adapter: EventStorePort | None = None

    @property
    def store(self) -> BaseEventStore | None:
        """The adapter, or `None` before `domain.init()`. The same object as `_adapter`."""
        # Every adapter the registry builds subclasses `BaseEventStore`, and
        # callers of `store` still use its delegating feature methods.
        return cast("BaseEventStore | None", self._adapter)

    def close(self) -> None:
        """Close the event store and release all connections.

        Delegates to the adapter's close() without clearing the
        reference, so the service remains usable (e.g., in test mode
        where the domain is still accessed after Engine.shutdown()).
        """
        if self._adapter is not None:
            self._adapter.close()
            logger.debug("Event store closed")

    def _build_adapter(self) -> EventStorePort:
        configured_event_store = self.domain.config["event_store"]
        event_store_cls = event_store_registry.get(configured_event_store["provider"])
        # A domain has one event store, so its adapter is always named "default".
        adapter: EventStorePort = event_store_cls(
            "default", self.domain, configured_event_store
        )
        return adapter

    def _initialize(self) -> None:
        logger.debug("Initializing Event Store...")

        # Close any previously-initialized event store to release connections
        # before creating a new one (prevents connection pool exhaustion on
        # repeated domain.init() calls).
        if self._adapter is not None:
            self._adapter.close()

        # An event store is always present by default. If not configured
        # explicitly, a memory-based event store is used.
        self._adapter = self._build_adapter()

    def _require_adapter(self) -> EventStorePort:
        if self._adapter is None:
            raise ConfigurationError(
                "Event store is not initialized. Call `domain.init()` first.",
                code=DiagnosticCode.CONFIG_EVENT_STORE_NOT_INITIALIZED,
                location="EventStore._require_adapter",
            )
        return self._adapter

    # ------------------------------------------------------------------
    # Forwarders to the adapter
    # ------------------------------------------------------------------

    @property
    def capabilities(self) -> EventStoreCapabilities:
        """The guarantees the adapter makes."""
        return self._require_adapter().capabilities

    def clear(self) -> None:
        """Delete every message. Test-harness use only."""
        self._require_adapter().clear()

    def ping(self) -> bool:
        """Return whether the store answers."""
        return self._require_adapter().ping()

    def health(self) -> EventStoreHealth:
        """Return the store's health record."""
        return self._require_adapter().health()

    def get_connection(self) -> object:
        """Return the adapter's native client, or `None` for an adapter without one."""
        return self._require_adapter().get_connection()

    def _write_message(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        return self._require_adapter().write_message(
            stream_name, message_type, data, metadata, expected_version
        )

    def _get_last_stream_message(self, stream_name: str) -> RawMessage | None:
        return self._require_adapter().get_last_stream_message(stream_name)

    def _stream_ids(self, category: str) -> list[str]:
        return self._require_adapter().stream_ids(category)

    def _get_all_messages(
        self, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        return self._require_adapter().get_all_messages(position, limit)

    def _get_category_messages(
        self, category: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        return self._require_adapter().get_category_messages(category, position, limit)

    def _get_stream_messages(
        self, stream_name: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        return self._require_adapter().get_stream_messages(stream_name, position, limit)

    # ------------------------------------------------------------------
    # Raw reads
    # ------------------------------------------------------------------

    def _read_raw(
        self, stream: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        """Read ``stream`` through the Port member for its scope.

        ``$all`` reads the whole store, a name with no ``-`` reads a category,
        and any other name reads one stream.
        """
        adapter = self._require_adapter()
        if stream == "$all":
            return adapter.get_all_messages(position, limit)
        if "-" not in stream:
            return adapter.get_category_messages(stream, position, limit)
        return adapter.get_stream_messages(stream, position, limit)

    def _read_last_raw(self, stream: str) -> RawMessage | None:
        """Read the newest row of ``stream``, with the scope rule of ``_read_raw``."""
        adapter = self._require_adapter()
        if stream == "$all":
            return adapter.get_last_message()
        if "-" not in stream:
            return adapter.get_last_category_message(stream)
        return adapter.get_last_stream_message(stream)

    # ------------------------------------------------------------------
    # Reading messages
    # ------------------------------------------------------------------

    @staticmethod
    def category(stream: str) -> str:
        """Return the category of ``stream``: the part before the first ``-``.

        Returns ``""`` for an empty or ``None`` stream name.
        """
        if not stream:
            return ""

        stream_category, _, _ = stream.partition("-")
        return stream_category

    def read(self, stream: str, position: int = 0, limit: int = 1000) -> list[Message]:
        """Return up to ``limit`` messages of ``stream`` from ``position``.

        ``stream`` is ``$all``, a category, or a ``category-id`` stream. Snapshot
        rows count toward ``limit`` and are left out of the result.
        """
        messages, _ = self._read_with_snapshot_positions(
            stream, position=position, limit=limit
        )
        return messages

    def _read_with_snapshot_positions(
        self, stream: str, position: int = 0, limit: int = 1000
    ) -> tuple[list[Message], list[int]]:
        """Read like ``read``, and also return where the skipped snapshot rows sat.

        Returns the deserialized messages in store order, and the
        ``global_position`` of every snapshot row the read skipped. A snapshot
        row with no ``global_position`` is left out of the position list.
        """
        raw_messages = self._read_raw(stream, position=position, limit=limit)

        # Skip snapshot rows: they carry an aggregate's state with no metadata,
        # so they are neither events nor commands and would raise on deserialize.
        # A scope that spans snapshot streams (``$all``, a ``:snapshot-`` stream)
        # would otherwise fail the whole read.
        messages: list[Message] = []
        snapshot_positions: list[int] = []
        for raw_message in raw_messages:
            if _is_snapshot_row(raw_message):
                global_position = raw_message.get("global_position")
                if global_position is not None:
                    snapshot_positions.append(global_position)
            else:
                messages.append(Message.deserialize(raw_message))
        return messages, snapshot_positions

    def read_all(
        self, stream: str = "$all", *, page_size: int = 1000
    ) -> Iterator[Message]:
        """Yield every message in ``stream``, reading the store in pages of ``page_size`` rows.

        A single ``read`` returns at most ``limit`` rows, so use this for
        a read that must be complete, such as a projection rebuild or a backup.
        Memory use stays bounded whatever the size of the stream. Snapshot rows
        are skipped, so only events and commands are yielded.

        Args:
            stream: The stream to read. ``$all`` (default), a category, or a
                specific ``category-id`` stream.
            page_size: Number of rows to read from the store per page.

        Yields:
            Every `Message` in ``stream``, in read order, with no gaps and
            no duplicates across page boundaries.

        Raises:
            IncorrectUsageError: If ``page_size`` is not a positive integer, or
                a stored row is missing its position.
        """
        for raw_message in self._read_all_raw(stream, page_size=page_size):
            yield Message.deserialize(raw_message)

    def _read_all_raw(
        self, stream: str = "$all", *, page_size: int = 1000
    ) -> Iterator[RawMessage]:
        """Yield every raw row in ``stream`` except snapshot rows, paging like ``read_all``.

        A caller that filters on a raw field such as ``type`` uses this to
        deserialize only the rows it keeps.

        Raises:
            IncorrectUsageError: If ``page_size`` is not a positive integer, or
                a stored row is missing its position.
        """
        # Check the type before the value: a float or ``None`` slipping through
        # would flow into the adapter's row limit and either page oddly or raise
        # a bare ``TypeError`` far from the cause. ``bool`` is an ``int``, and
        # ``True`` (== 1) is harmless, so it is not special-cased.
        if not isinstance(page_size, int) or page_size < 1:
            raise IncorrectUsageError(
                f"`page_size` must be a positive integer, got {page_size!r}"
            )

        # A category read (`$all` or a bare category) pages by `global_position`;
        # a specific stream pages by its per-stream `position`. `category(stream)`
        # strips the `-id` suffix, so it equals `stream` only for a category/$all.
        pages_by_global_position = stream == self.category(stream)

        cursor = 0
        while True:
            raw_page = self._read_raw(stream, position=cursor, limit=page_size)
            for raw_message in raw_page:
                if _is_snapshot_row(raw_message):
                    continue
                yield raw_message

            # A short raw page is the last page: the store had no more rows to
            # fill it. Terminate on the *raw* count, not the yielded count, so a
            # page whose rows include snapshots is not mistaken for the end. This
            # also terminates the empty-stream case after one read.
            if len(raw_page) < page_size:
                return

            cursor = _next_cursor(raw_page[-1], pages_by_global_position)

    def read_last_message(self, stream: str) -> Message | None:
        """Return the newest event or command of ``stream``, or ``None`` when it has none."""
        raw_message = self._read_last_raw(stream)
        if raw_message is None:
            return None

        # The newest row can be a snapshot (aggregate state, no metadata), which
        # is neither an event nor a command and would raise on deserialize. In
        # practice this is the `$all` scan (outbox reconciliation reads it that
        # way), where snapshot streams interleave with event streams; a specific
        # or bare-category read filters to `{category}-` and never sees a
        # `{category}:snapshot-` row, so its tail is already an event. Skip back
        # to the newest actual message so those callers do not crash.
        if _is_snapshot_row(raw_message):
            raw_message = self._last_non_snapshot_message(stream, raw_message)
            if raw_message is None:
                return None

        return Message.deserialize(raw_message)

    def _last_non_snapshot_message(
        self, stream: str, tail: RawMessage
    ) -> RawMessage | None:
        """The newest event/command row in ``stream`` at or before ``tail``.

        Consulted when ``_read_last_raw`` returns a snapshot as the tail
        row, which is the ``$all`` scan, where snapshot streams interleave with
        event streams. Walks backward from the tail in
        ``_SNAPSHOT_TAIL_WINDOW``-sized windows keyed on ``global_position``, so
        skipping a trailing snapshot costs a small read near the tail, not a
        full scan from the start, and a store larger than one window does not
        return a stale non-tail row. Within a window the newest is chosen by
        ``global_position`` rather than trusting row order, since some adapters
        read ``$all`` with no ``ORDER BY``.
        """
        hi: int = tail.get("global_position", -1)
        while hi >= 0:
            low = max(0, hi - _SNAPSHOT_TAIL_WINDOW + 1)
            # ``_read_raw`` returns rows with ``global_position >= low`` in ascending
            # order, so the first ``_SNAPSHOT_TAIL_WINDOW`` of them cover all of
            # ``[low, hi]`` (that range spans at most that many positions); the
            # ``<= hi`` filter drops any row past the tail that a gap let in.
            candidates = [
                raw_message
                for raw_message in self._read_raw(
                    stream, position=low, limit=_SNAPSHOT_TAIL_WINDOW
                )
                if raw_message.get("global_position", -1) <= hi
                and not _is_snapshot_row(raw_message)
            ]
            if candidates:
                return max(candidates, key=lambda m: m.get("global_position", -1))
            if low == 0:
                return None
            hi = low - 1
        return None

    def category_head_position(self, category: str) -> int:
        """Return the ``global_position`` of the newest row in ``category``.

        For ``$all`` the row can be a snapshot row, because this reads raw rows
        and skips nothing.

        Subscription lag monitoring uses it to find how far a subscription is
        behind the head of its category.

        Args:
            category: A category, such as ``test::user``, or ``$all`` for the
                whole store. A stream name, such as ``test::user-1``, gives
                the newest row of that one stream.

        Returns:
            The ``global_position`` of the newest row, or ``-1`` when the
            category has no rows.
        """
        # A subscription whose category names one stream passes that stream
        # here, so a name with a ``-`` reads the stream through the
        # ``_read_raw`` scope rule; Message DB finds no category of that name.
        message = self._read_last_raw(category)
        return message["global_position"] if message else -1

    # ------------------------------------------------------------------
    # Writing messages
    # ------------------------------------------------------------------

    def append(self, message_object: BaseEvent | BaseCommand) -> int:
        """Write an event or command to its stream and return its stream position.

        Raises:
            ExpectedVersionError: When the message carries an expected version
                that is not the stream's current version. Nothing is written.
        """
        adapter = self._require_adapter()
        tracer = self.domain.tracer

        with tracer.start_as_current_span(
            "protean.event_store.append",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            message = Message.from_domain_object(message_object)
            assert message.metadata is not None, "Message metadata cannot be None"

            stream = message.metadata.headers.stream
            message_type = message.metadata.headers.type
            assert stream is not None, "Message stream cannot be None"
            assert message_type is not None, "Message type cannot be None"

            span.set_attribute("protean.event_store.stream", stream)
            span.set_attribute("protean.event_store.message_type", message_type)

            try:
                position = adapter.write_message(
                    stream,
                    message_type,
                    message.data,
                    metadata=message.metadata.to_dict(),
                    expected_version=message.metadata.domain.expected_version
                    if message.metadata.domain
                    else None,
                )

                span.set_attribute("protean.event_store.position", position)
                return position
            except Exception as exc:  # marks the span as failed, then re-raises
                set_span_error(span, exc)
                raise

    # ------------------------------------------------------------------
    # Loading aggregates
    # ------------------------------------------------------------------

    def load_aggregate(
        self,
        part_of: type[BaseAggregate],
        identifier: str,
        *,
        at_version: int | None = None,
        as_of: datetime | None = None,
    ) -> BaseAggregate | None:
        """Load an aggregate by replaying its events.

        By default, rebuilds the aggregate in its current (latest) state. When
        ``at_version`` or ``as_of`` is given, rebuilds its state at that point
        in history.

        Args:
            part_of: The EventSourced Aggregate's class.
            identifier: Unique aggregate identifier.
            at_version: Reconstitute to this exact version (0-indexed).
                Version 0 is the state after the first event.
            as_of: Reconstitute the aggregate as of this timestamp.
                Only events written on or before ``as_of`` are applied.

        Returns:
            The aggregate, or ``None`` when its stream holds no events.

        Raises:
            ObjectNotFoundError: If ``at_version`` is past the aggregate's latest
                version, or no event was written on or before ``as_of``.
        """
        if as_of is not None:
            return self._load_aggregate_as_of(part_of, identifier, as_of)
        if at_version is not None:
            return self._load_aggregate_at_version(part_of, identifier, at_version)
        return self._load_aggregate_current(part_of, identifier)

    def _read_stream_fully(
        self,
        stream: str,
        start_position: int = 0,
        max_rows: int | None = None,
        *,
        page_size: int = 1000,
    ) -> deque[RawMessage]:
        """Read the rows of ``stream``, paging past the per-read page size.

        A single ``_read_raw`` returns at most one page, and an aggregate that
        warranted a snapshot can hold more events than one page, so a caller that
        needs the whole stream (or a bounded prefix of it) has to page or it
        rebuilds an incomplete aggregate. ``start_position`` begins the read past
        a snapshot's version to pick up only later events; ``max_rows`` bounds the
        read to a prefix, which a temporal query uses to stop at the requested
        version; ``None`` reads to the end. ``page_size`` is the number of rows
        per ``_read_raw``. A continuation shorter than one page still costs a single
        read. Reads are inclusive, so each page resumes one
        position past the last row seen.
        """
        rows: deque[RawMessage] = deque()
        position = start_position
        while max_rows is None or len(rows) < max_rows:
            batch = (
                page_size if max_rows is None else min(page_size, max_rows - len(rows))
            )
            page = self._read_raw(stream, position=position, limit=batch)
            if not page:
                break
            rows.extend(page)
            if len(page) < batch:
                break
            position = page[-1]["position"] + 1
        return rows

    def _load_aggregate_current(
        self, part_of: type[BaseAggregate], identifier: str
    ) -> BaseAggregate | None:
        """Load the aggregate at its latest version (existing behaviour)."""
        adapter = self._require_adapter()
        snapshot_message = adapter.get_last_stream_message(
            f"{part_of.meta_.stream_category}:snapshot-{identifier}"
        )

        aggregate: BaseAggregate | None = None
        position_in_snapshot: int = 0
        event_stream: deque[RawMessage] = deque()

        if snapshot_message:
            try:
                # We have a snapshot, so initialize aggregate from snapshot
                #   and apply subsequent events
                aggregate = part_of(**(snapshot_message["data"] or {}))
            except ValidationError as exc:
                # The snapshot predates the current schema (a field was
                # renamed, removed, or newly required), so it no longer
                # constructs. A snapshot is a rebuildable cache over the
                # authoritative event stream, so discard it, log a warning, and
                # fall back to a full replay below. Treating it as absent also
                # lets the threshold check rewrite a fresh snapshot.
                _log_snapshot_discarded(part_of, identifier, exc)
                snapshot_message = None
            else:
                position_in_snapshot = aggregate._version
                # Page from just past the snapshot so a continuation longer than
                # one read page is not truncated (a short continuation is still
                # one read).
                event_stream = self._read_stream_fully(
                    f"{part_of.meta_.stream_category}-{identifier}",
                    start_position=aggregate._version + 1,
                )
                for event_message in event_stream:
                    event = Message.deserialize(event_message).to_domain_object()
                    aggregate._apply(event)

        if aggregate is None:
            # No usable snapshot, so initialize aggregate from the full event
            # stream, paging to the end so a stream larger than one read is not
            # truncated into an incomplete aggregate.
            event_stream = self._read_stream_fully(
                f"{part_of.meta_.stream_category}-{identifier}"
            )

            if not event_stream:
                return None

            events: list[BaseEvent | BaseCommand] = [
                Message.deserialize(event_message).to_domain_object()
                for event_message in event_stream
            ]

            aggregate = part_of.from_events(events)

        # Create a new snapshot once the event count reaches the threshold.
        # This runs inline (synchronous write) for simplicity — the aggregate
        # is already in memory and the write is to a separate snapshot stream.
        if (
            snapshot_message
            and len(event_stream) > 1
            and (
                event_stream[-1]["position"] - position_in_snapshot
                >= self.domain.config["snapshot_threshold"]
            )
        ) or (
            not snapshot_message
            and len(event_stream) >= self.domain.config["snapshot_threshold"]
        ):
            # Snapshot is of type "SNAPSHOT" and contains only the aggregate's data
            #   (no metadata, so no event type)
            # This makes reconstruction of the aggregate from the snapshot easier,
            #   and also avoids spurious data just to satisfy Metadata's structure
            #   and conditions.
            adapter.write_message(
                f"{part_of.meta_.stream_category}:snapshot-{identifier}",
                SNAPSHOT_TYPE,
                aggregate.to_dict(),
            )

        return aggregate

    def _load_aggregate_at_version(
        self,
        part_of: type[BaseAggregate],
        identifier: str,
        at_version: int,
    ) -> BaseAggregate | None:
        """Load an aggregate at a specific version.

        Version is 0-indexed: version 0 = state after the first event.
        Snapshots are leveraged when the snapshot version <= ``at_version``.
        No new snapshots are created for temporal queries.
        """
        stream = f"{part_of.meta_.stream_category}-{identifier}"
        aggregate = _aggregate_from_snapshot(
            self, part_of, identifier, stream, at_version
        )

        if aggregate is None:
            # No usable snapshot — replay from the beginning up to the requested
            # version, paging so a version beyond one read page is not truncated.
            aggregate = _aggregate_from_events(self, part_of, stream, at_version)
            if aggregate is None:
                return None

        # Validate we reached the requested version
        if aggregate._version < at_version:
            raise ObjectNotFoundError(
                f"`{part_of.__name__}` object with identifier {identifier} "
                f"does not have version {at_version}. "
                f"Latest version is {aggregate._version}."
            )

        return aggregate

    def _load_aggregate_as_of(
        self,
        part_of: type[BaseAggregate],
        identifier: str,
        as_of: datetime,
    ) -> BaseAggregate | None:
        """Load an aggregate as of a specific timestamp.

        Snapshots are skipped entirely: events are read from position 0 and
        filtered by their write timestamp.  Only events with
        ``time <= as_of`` are applied.
        """
        stream = f"{part_of.meta_.stream_category}-{identifier}"
        # Page the whole stream so a timestamp filter over more than one read
        # page is not applied to a truncated prefix.
        event_stream = self._read_stream_fully(stream)

        if not event_stream:
            return None

        # Filter events by write timestamp
        filtered_messages = []
        for msg in event_stream:
            event_time = _parse_event_time(msg.get("time"))
            if event_time is not None:
                et, co = _make_comparable(event_time, as_of)
                if et <= co:
                    filtered_messages.append(msg)

        if not filtered_messages:
            raise ObjectNotFoundError(
                f"`{part_of.__name__}` object with identifier {identifier} "
                f"has no events on or before {as_of}."
            )

        events = [
            Message.deserialize(msg).to_domain_object() for msg in filtered_messages
        ]
        aggregate = part_of.from_events(events)

        return aggregate

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def create_snapshot(self, part_of: type[BaseAggregate], identifier: str) -> bool:
        """Create a snapshot for a specific event-sourced aggregate instance.

        Rebuilds the aggregate from its full event stream and writes its current
        state to the snapshot stream. The snapshot is written whatever the
        snapshot threshold.

        Args:
            part_of: The EventSourced Aggregate class.
            identifier: Unique aggregate identifier.

        Returns:
            True if a snapshot was created.

        Raises:
            IncorrectUsageError: If the aggregate is not event-sourced.
            ObjectNotFoundError: If no events exist for the given identifier.
        """
        adapter = self._require_adapter()
        if not part_of.meta_.is_event_sourced:
            raise IncorrectUsageError(
                f"`{part_of.__name__}` is not an event-sourced aggregate"
            )

        # Read ALL events (fresh reconstruction, not from existing snapshot),
        # paging the whole stream so the snapshot reflects the head state even
        # when the stream is longer than one read page.
        event_stream = self._read_stream_fully(
            f"{part_of.meta_.stream_category}-{identifier}"
        )

        if not event_stream:
            raise ObjectNotFoundError(
                f"`{part_of.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        events = [Message.deserialize(msg).to_domain_object() for msg in event_stream]
        aggregate = part_of.from_events(events)

        adapter.write_message(
            f"{part_of.meta_.stream_category}:snapshot-{identifier}",
            SNAPSHOT_TYPE,
            aggregate.to_dict(),
        )

        return True

    def create_snapshots(self, part_of: type[BaseAggregate]) -> int:
        """Create snapshots for all instances of an event-sourced aggregate.

        Discovers all unique aggregate identifiers in the stream category,
        then creates a snapshot for each.

        Args:
            part_of: The EventSourced Aggregate class

        Returns:
            Number of snapshots created.

        Raises:
            IncorrectUsageError: If the aggregate is not event-sourced.
        """
        adapter = self._require_adapter()
        if not part_of.meta_.is_event_sourced:
            raise IncorrectUsageError(
                f"`{part_of.__name__}` is not an event-sourced aggregate"
            )

        identifiers = adapter.stream_ids(part_of.meta_.stream_category)

        # With fact_events enabled, persisting also writes a
        # ``{category}-fact-{id}`` stream that shares the category prefix. Those
        # are not aggregate instances and have no ``@apply`` handler, so exclude
        # them. Scoped to fact_events so an ordinary instance whose identifier
        # happens to start with ``fact-`` is never wrongly skipped.
        if part_of.meta_.fact_events:
            identifiers = [
                identifier
                for identifier in identifiers
                if not _is_fact_stream_identifier(identifier)
            ]

        count = 0
        for identifier in identifiers:
            self.create_snapshot(part_of, identifier)
            count += 1

        return count

    # ------------------------------------------------------------------
    # Causation tracing
    # ------------------------------------------------------------------

    def trace_causation(self, message_id: str | Message) -> list[Message]:
        """Return the causation chain from the root message down to ``message_id``.

        Args:
            message_id: A Protean message ID string (``headers.id``) or
                a `Message` object.

        Returns:
            `Message` objects in causal order, root first and the given message
            last. Empty when ``message_id`` is a `Message` the store does not
            hold.

        Raises:
            ValueError: ``message_id`` is a string that no message in the
                store has, or a `Message` with no ``headers.id``. A `Message`
                the store does not hold is not looked up and raises nothing.
        """
        return causation.trace_causation(self._require_adapter(), message_id)

    def trace_effects(
        self, message_id: str | Message, *, recursive: bool = True
    ) -> list[Message]:
        """Return the messages caused by ``message_id``.

        Args:
            message_id: A Protean message ID string (``headers.id``) or
                a `Message` object.
            recursive: If ``True`` (default), return the full subtree of
                effects.  If ``False``, return only direct children.

        Returns:
            `Message` objects caused by the given message, ordered by
            ``global_position``. The given message itself is not included.

        Raises:
            ValueError: ``message_id`` is a string that no message in the
                store has, or a `Message` with no ``headers.id``. A `Message`
                the store does not hold is not looked up and raises nothing.
        """
        return causation.trace_effects(
            self._require_adapter(), message_id, recursive=recursive
        )

    def build_causation_tree(self, correlation_id: str) -> CausationNode | None:
        """Build a full causation tree for a correlation ID.

        Returns the root node of the tree with children recursively populated.

        Args:
            correlation_id: The correlation ID to trace.

        Returns:
            Root [`CausationNode`][protean.infra.causation.CausationNode] with
            children, or ``None`` if no messages found.
        """
        return causation.build_causation_tree(self._require_adapter(), correlation_id)

    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------

    def verify(self) -> IntegrityReport:
        """Check the store's internal invariants and report every violation.

        Reads the whole store and changes nothing. See
        [`protean.infra.integrity.verify`][protean.infra.integrity.verify] for
        the invariants it checks.

        Returns:
            An [`IntegrityReport`][protean.infra.integrity.IntegrityReport] of
            the violations found. ``ok`` is ``True`` when there are none.
        """
        return integrity.verify(self._require_adapter())
