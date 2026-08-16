from __future__ import annotations

from abc import ABCMeta, abstractmethod
from collections import defaultdict, deque
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from protean.domain import Domain

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError, ObjectNotFoundError
from protean.utils.eventing import Message
from protean.utils.telemetry import set_span_error


@dataclass
class CausationNode:
    """A node in the causation tree, representing a single message and its effects."""

    message_id: str
    message_type: str
    kind: str  # "EVENT" or "COMMAND"
    stream: str
    time: str | None
    global_position: int | None
    children: list[CausationNode] = dc_field(default_factory=list)
    handler: str | None = None
    duration_ms: float | None = None
    delta_ms: float | None = None


@dataclass(frozen=True)
class IntegrityViolation:
    """A single violation of the event store's internal invariants.

    ``kind`` is a stable machine token (one of the ``VERIFY_*`` constants on
    [`BaseEventStore`][protean.port.event_store.BaseEventStore]); ``stream`` and
    ``position`` name where the violation was found (either may be ``None`` when
    it is not stream- or position-specific); ``detail`` is a human-readable
    explanation.
    """

    kind: str
    stream: str | None
    position: int | None
    detail: str


@dataclass(frozen=True)
class IntegrityReport:
    """The result of [`verify`][protean.port.event_store.BaseEventStore.verify].

    ``message_count`` is every message scanned; ``stream_count`` is the number of
    streams that held at least one positioned message. ``ok`` is derived: a
    report is ``ok`` exactly when it carries no violations, so the two can never
    disagree. This shape (with ``ok`` included) is the documented, stable contract
    behind ``protean eventstore verify --json``.
    """

    message_count: int
    stream_count: int
    violations: list[IntegrityViolation] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether the scan found no violations."""
        return not self.violations

    def as_dict(self) -> dict[str, Any]:
        """Serialize to the ``--json`` ``data`` payload, ``ok`` included.

        ``dataclasses.asdict`` omits the ``ok`` property, so build the wire
        payload explicitly to keep ``data.ok`` in the contract.
        """
        return {
            "ok": self.ok,
            "message_count": self.message_count,
            "stream_count": self.stream_count,
            "violations": [asdict(v) for v in self.violations],
        }


class BaseEventStore(metaclass=ABCMeta):
    """This class outlines the base event store capabilities
    to be implemented in all supported event store adapters.

    It is also a marker interface for registering event store
    classes with the domain.
    """

    def __init__(self, name: str, domain: Domain, conn_info: dict[str, str]) -> None:
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

    def close(self) -> None:
        """Close the event store and release all connections.

        Subclasses that hold external resources (connection pools, sockets,
        etc.) should override this to perform cleanup.  The default
        implementation is a no-op so that adapters without external
        resources (e.g. the in-memory store) work without changes.
        """

    @abstractmethod
    def _write(
        self,
        stream_name: str,
        message_type: str,
        data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        """Write a message to the event store.

        Returns the position of the message in the stream.

        Implemented by the concrete event store adapter.
        """

    @abstractmethod
    def _read(
        self,
        stream_name: str,
        sql: str | None = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read messages from the event store.

        Implemented by the concrete event store adapter.
        """

    @abstractmethod
    def _read_last_message(self, stream_name: str) -> dict[str, Any] | None:
        """Read the last message from the event store.

        Implemented by the concrete event store adapter.
        """

    def category(self, stream: str) -> str:
        if not stream:
            return ""

        stream_category, _, _ = stream.partition("-")
        return stream_category

    def read(
        self,
        stream: str,
        sql: str | None = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> list[Message]:
        raw_messages = self._read(
            stream, sql=sql, position=position, no_of_messages=no_of_messages
        )

        messages = [Message.deserialize(raw_message) for raw_message in raw_messages]

        return messages

    def read_all(
        self, stream: str = "$all", *, page_size: int = 1000
    ) -> Iterator[Message]:
        """Yield every message in ``stream``, paging through the store in bounded batches.

        A cold-load read that must be complete (a full projection rebuild, a
        backup, an integrity check) cannot rely on a single large ``read`` with a
        sentinel ``no_of_messages``: past the cap it silently truncates. This
        iterator loops ``read`` in ``page_size`` batches and advances a cursor
        until a short page signals the end, so it reads the whole stream at a
        bounded memory cost regardless of size.

        The cursor field follows the stream shape (ADR-0024): ``$all`` and a bare
        category page by ``global_position``; a specific stream (``category-id``)
        pages by its own per-stream ``position``. Reads are inclusive
        (``>= position``), so each next page resumes one past the last row seen,
        which avoids re-emitting the boundary row.

        Args:
            stream: The stream to read. ``$all`` (default), a category, or a
                specific ``category-id`` stream.
            page_size: Number of messages to read per underlying ``read`` call.

        Yields:
            Every `Message` in ``stream``, in read order, with no gaps and
            no duplicates across page boundaries.

        Raises:
            IncorrectUsageError: If ``page_size`` is not a positive integer.
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
            page = self.read(stream, position=cursor, no_of_messages=page_size)
            yield from page

            # A short page is the last page: the store had no more rows to fill
            # it. This also terminates the empty-stream case after one read.
            if len(page) < page_size:
                return

            cursor = self._next_cursor(page[-1], pages_by_global_position)

    @staticmethod
    def _next_cursor(message: Message, by_global_position: bool) -> int:
        """The ``position`` to resume a paged read after ``message``.

        Reads are inclusive, so resume one past the last row seen. A persisted
        message always carries the relevant position; a missing one is a corrupt
        row that would otherwise loop or truncate the read silently, so raise.
        ``EventStoreMeta`` is attached when *either* position is present, so a row
        can carry an ``event_store`` whose chosen field is still ``None``.
        """
        event_store = message.metadata.event_store if message.metadata else None
        last: int | None = None
        if event_store is not None:
            last = (
                event_store.global_position
                if by_global_position
                else event_store.position
            )
        if last is None:
            raise IncorrectUsageError(
                "Cannot page the event store: a message is missing its position."
            )
        return last + 1

    def read_last_message(self, stream: str) -> Message | None:
        raw_message = self._read_last_message(stream)
        if raw_message:
            return Message.deserialize(raw_message)

        return None

    def append(self, object: BaseEvent | BaseCommand) -> int:
        tracer = self.domain.tracer

        with tracer.start_as_current_span(
            "protean.event_store.append",
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            message = Message.from_domain_object(object)
            assert message.metadata is not None, "Message metadata cannot be None"

            stream = message.metadata.headers.stream
            message_type = message.metadata.headers.type
            assert stream is not None, "Message stream cannot be None"
            assert message_type is not None, "Message type cannot be None"

            span.set_attribute("protean.event_store.stream", stream)
            span.set_attribute("protean.event_store.message_type", message_type)

            try:
                position = self._write(
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
            except Exception as exc:
                set_span_error(span, exc)
                raise

    def load_aggregate(
        self,
        part_of: type[BaseAggregate],
        identifier: str,
        *,
        at_version: int | None = None,
        as_of: datetime | None = None,
    ) -> BaseAggregate | None:
        """Load an aggregate from underlying events.

        By default, reconstitutes the aggregate to its current (latest) state.
        When ``at_version`` or ``as_of`` is provided, reconstitutes a historical
        snapshot of the aggregate: a *temporal query*.

        Args:
            part_of: The EventSourced Aggregate's class.
            identifier: Unique aggregate identifier.
            at_version: Reconstitute to this exact version (0-indexed).
                Version 0 is the state after the first event.
            as_of: Reconstitute the aggregate as of this timestamp.
                Only events written on or before ``as_of`` are applied.

        Returns:
            The fully-formed aggregate, or ``None`` when no events exist
            (and no temporal param was given that would raise instead).
        """
        if as_of is not None:
            return self._load_aggregate_as_of(part_of, identifier, as_of)
        if at_version is not None:
            return self._load_aggregate_at_version(part_of, identifier, at_version)
        return self._load_aggregate_current(part_of, identifier)

    # ------------------------------------------------------------------
    # Private helpers for load_aggregate
    # ------------------------------------------------------------------

    def _load_aggregate_current(
        self, part_of: type[BaseAggregate], identifier: str
    ) -> BaseAggregate | None:
        """Load the aggregate at its latest version (existing behaviour)."""
        snapshot_message = self._read_last_message(
            f"{part_of.meta_.stream_category}:snapshot-{identifier}"
        )

        position_in_snapshot: int = 0
        if snapshot_message:
            # We have a snapshot, so initialize aggregate from snapshot
            #   and apply subsequent events
            aggregate = part_of(**snapshot_message["data"])
            position_in_snapshot = aggregate._version

            event_stream = deque(
                self._read(
                    f"{part_of.meta_.stream_category}-{identifier}",
                    position=aggregate._version + 1,
                )
            )

            events: list[BaseEvent | BaseCommand] = []
            for event_message in event_stream:
                event = Message.deserialize(event_message).to_domain_object()
                aggregate._apply(event)
        else:
            # No snapshot, so initialize aggregate from events
            event_stream = deque(
                self._read(f"{part_of.meta_.stream_category}-{identifier}")
            )

            if not event_stream:
                return None

            events = []
            for event_message in event_stream:
                events.append(Message.deserialize(event_message).to_domain_object())

            aggregate = part_of.from_events(events)

        # Create a new snapshot if the event count exceeds the threshold.
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
            self._write(
                f"{part_of.meta_.stream_category}:snapshot-{identifier}",
                "SNAPSHOT",
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
        snapshot_message = self._read_last_message(
            f"{part_of.meta_.stream_category}:snapshot-{identifier}"
        )

        aggregate: BaseAggregate | None = None

        if snapshot_message:
            snapshot_version: int = snapshot_message["data"].get("_version", -1)
            if snapshot_version <= at_version:
                # Snapshot is usable — initialize from it
                aggregate = part_of(**snapshot_message["data"])
                remaining = at_version - aggregate._version
                if remaining > 0:
                    event_stream = self._read(
                        stream,
                        position=aggregate._version + 1,
                        no_of_messages=remaining,
                    )
                    for event_message in event_stream:
                        event = Message.deserialize(event_message).to_domain_object()
                        aggregate._apply(event)
                # else: snapshot is exactly at the requested version

        if aggregate is None:
            # No usable snapshot — replay from the beginning
            event_stream = self._read(
                stream,
                no_of_messages=at_version + 1,
            )

            if not event_stream:
                return None

            events = [
                Message.deserialize(msg).to_domain_object() for msg in event_stream
            ]
            aggregate = part_of.from_events(events)

        # Validate we reached the requested version
        if aggregate._version < at_version:
            raise ObjectNotFoundError(
                f"`{part_of.__name__}` object with identifier {identifier} "
                f"does not have version {at_version}. "
                f"Latest version is {aggregate._version}."
            )

        return aggregate

    @staticmethod
    def _parse_event_time(raw_time: Any) -> datetime | None:
        """Normalise a raw ``time`` value from an event message to ``datetime``.

        Adapters may return the ``time`` field as either a ``datetime`` object
        (e.g. MessageDB via psycopg2) or as an ISO-8601 string (e.g. the
        memory adapter's ``to_dict()``).
        """
        if raw_time is None:
            return None
        if isinstance(raw_time, datetime):
            return raw_time
        if isinstance(raw_time, str):
            return datetime.fromisoformat(raw_time)
        return None

    @staticmethod
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
        event_stream = self._read(stream)

        if not event_stream:
            return None

        # Filter events by write timestamp
        filtered_messages = []
        for msg in event_stream:
            event_time = self._parse_event_time(msg.get("time"))
            if event_time is not None:
                et, co = self._make_comparable(event_time, as_of)
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

    def create_snapshot(self, part_of: type[BaseAggregate], identifier: str) -> bool:
        """Create a snapshot for a specific event-sourced aggregate instance.

        Reads the full event stream for the aggregate, reconstructs it via
        ``from_events()``, and writes a snapshot to the snapshot stream.
        This bypasses the snapshot threshold -- manual triggers always create
        a snapshot regardless of event count.

        Args:
            part_of: The EventSourced Aggregate class
            identifier: Unique aggregate identifier

        Returns:
            True if a snapshot was created.

        Raises:
            IncorrectUsageError: If the aggregate is not event-sourced.
            ObjectNotFoundError: If no events exist for the given identifier.
        """
        if not part_of.meta_.is_event_sourced:
            raise IncorrectUsageError(
                f"`{part_of.__name__}` is not an event-sourced aggregate"
            )

        # Read ALL events (fresh reconstruction, not from existing snapshot)
        event_stream = deque(
            self._read(f"{part_of.meta_.stream_category}-{identifier}")
        )

        if not event_stream:
            raise ObjectNotFoundError(
                f"`{part_of.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        events = [Message.deserialize(msg).to_domain_object() for msg in event_stream]
        aggregate = part_of.from_events(events)

        self._write(
            f"{part_of.meta_.stream_category}:snapshot-{identifier}",
            "SNAPSHOT",
            aggregate.to_dict(),
        )

        return True

    @staticmethod
    def _is_fact_stream_identifier(identifier: str) -> bool:
        """Whether a parsed identifier belongs to a fact-event stream.

        Fact streams are named ``{category}-fact-{identifier}``, so their parsed
        identifier segment starts with ``fact-``. They hold ``...FactEvent``
        records, not an aggregate instance's events. This is only consulted for
        aggregates with ``fact_events=True`` (see [`create_snapshots`][protean.port.event_store.BaseEventStore.create_snapshots]), so
        an ordinary instance whose identifier starts with ``fact-`` is unaffected
        unless its own aggregate also emits fact events.
        """
        return identifier.startswith("fact-")

    @abstractmethod
    def _stream_identifiers(self, stream_category: str) -> list[str]:
        """Return all unique aggregate identifiers for a given stream category.

        Stream names follow the pattern ``{category}-{identifier}``.
        Snapshot streams (``{category}:snapshot-{identifier}``) must be
        excluded.

        Implemented by the concrete event store adapter.

        Args:
            stream_category: The stream category to scan (e.g. ``test::user``)

        Returns:
            Sorted list of unique aggregate identifiers.
        """

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
        if not part_of.meta_.is_event_sourced:
            raise IncorrectUsageError(
                f"`{part_of.__name__}` is not an event-sourced aggregate"
            )

        identifiers = self._stream_identifiers(part_of.meta_.stream_category)

        # With fact_events enabled, persisting also writes a
        # ``{category}-fact-{id}`` stream that shares the category prefix. Those
        # are not aggregate instances and have no ``@apply`` handler, so exclude
        # them. Scoped to fact_events so an ordinary instance whose identifier
        # happens to start with ``fact-`` is never wrongly skipped.
        if part_of.meta_.fact_events:
            identifiers = [
                identifier
                for identifier in identifiers
                if not self._is_fact_stream_identifier(identifier)
            ]

        count = 0
        for identifier in identifiers:
            self.create_snapshot(part_of, identifier)
            count += 1

        return count

    # ------------------------------------------------------------------
    # Causation chain traversal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_message_id(msg: dict[str, Any]) -> str | None:
        """Extract the Protean message ID (headers.id) from a raw message dict."""
        metadata = msg.get("metadata")
        if not metadata or not isinstance(metadata, dict):
            return None
        headers = metadata.get("headers")
        if not headers or not isinstance(headers, dict):
            return None
        message_id: str | None = headers.get("id")
        return message_id

    @staticmethod
    def _extract_causation_id(msg: dict[str, Any]) -> str | None:
        """Extract causation_id from a raw message dict."""
        metadata = msg.get("metadata")
        if not metadata or not isinstance(metadata, dict):
            return None
        domain = metadata.get("domain")
        if not domain or not isinstance(domain, dict):
            return None
        causation_id: str | None = domain.get("causation_id")
        return causation_id

    @staticmethod
    def _extract_correlation_id(msg: dict[str, Any]) -> str | None:
        """Extract correlation_id from a raw message dict."""
        metadata = msg.get("metadata")
        if not metadata or not isinstance(metadata, dict):
            return None
        domain = metadata.get("domain")
        if not domain or not isinstance(domain, dict):
            return None
        correlation_id: str | None = domain.get("correlation_id")
        return correlation_id

    def _load_correlation_group(self, correlation_id: str) -> list[dict[str, Any]]:
        """Load all raw messages sharing a correlation_id from the event store.

        Reads ``$all`` and filters by ``correlation_id``.
        This is a debugging/inspection utility, not optimized for high-throughput.
        """
        all_messages = self._read("$all", no_of_messages=1_000_000)
        return [
            m for m in all_messages if self._extract_correlation_id(m) == correlation_id
        ]

    def _resolve_and_load_group(
        self, message_id: str | Message
    ) -> tuple[str, list[dict[str, Any]]]:
        """Resolve a message identifier and load its full correlation group.

        When ``message_id`` is a `Message`, the correlation ID is read
        directly from metadata (no scan required).  When it is a ``str``, a
        single pass over ``$all`` finds the message and its correlation group.

        Returns:
            Tuple of ``(resolved_message_id, correlation_group)``.

        Raises:
            ValueError: If the message cannot be found in the event store.
        """
        if isinstance(message_id, Message):
            mid = (
                message_id.metadata.headers.id
                if message_id.metadata and message_id.metadata.headers
                else None
            )
            cid = (
                message_id.metadata.domain.correlation_id
                if message_id.metadata and message_id.metadata.domain
                else None
            )
            if mid is None:
                raise ValueError("Message has no headers.id")
            if cid is None:
                return mid, []
            group = self._load_correlation_group(cid)
            return mid, group

        # String ID — single pass to find the target and its group
        all_messages = self._read("$all", no_of_messages=1_000_000)
        target_correlation_id: str | None = None
        for m in all_messages:
            if self._extract_message_id(m) == message_id:
                target_correlation_id = self._extract_correlation_id(m)
                break

        if target_correlation_id is None:
            raise ValueError(f"Message with ID '{message_id}' not found in event store")

        group = [
            m
            for m in all_messages
            if self._extract_correlation_id(m) == target_correlation_id
        ]
        return message_id, group

    # ------------------------------------------------------------------
    # Public causation chain API
    # ------------------------------------------------------------------

    def trace_causation(self, message_id: str | Message) -> list[Message]:
        """Walk UP the causation chain from a message to the root.

        Returns an ordered list of Messages from the root command (first)
        to the given message (last).  The given message itself is included.

        Args:
            message_id: A Protean message ID string (``headers.id``) or
                a `Message` object.

        Returns:
            List of `Message` objects in causal order (root first,
            target last).

        Raises:
            ValueError: If the message cannot be found in the event store.
        """
        mid, group = self._resolve_and_load_group(message_id)

        # Build lookup: headers.id -> raw_message
        by_id: dict[str, dict[str, Any]] = {}
        for m in group:
            hid = self._extract_message_id(m)
            if hid:
                by_id[hid] = m

        # Walk up from target to root
        chain: list[dict[str, Any]] = []
        current_id: str | None = mid
        visited: set[str] = set()

        while current_id and current_id not in visited:
            visited.add(current_id)
            raw_msg = by_id.get(current_id)
            if raw_msg is None:
                break
            chain.append(raw_msg)
            current_id = self._extract_causation_id(raw_msg)

        # Reverse so root is first
        chain.reverse()

        return [Message.deserialize(m) for m in chain]

    def trace_effects(
        self, message_id: str | Message, *, recursive: bool = True
    ) -> list[Message]:
        """Walk DOWN the causation chain to find all effects of a message.

        Returns messages that were caused by the given message, ordered by
        ``global_position`` (chronological order).

        Args:
            message_id: A Protean message ID string (``headers.id``) or
                a `Message` object.
            recursive: If ``True`` (default), return the full subtree of
                effects.  If ``False``, return only direct children.

        Returns:
            List of `Message` objects caused by the given message,
            in chronological order.  The given message itself is NOT included.

        Raises:
            ValueError: If the message cannot be found in the event store.
        """
        mid, group = self._resolve_and_load_group(message_id)

        # Build children lookup: causation_id -> [raw_messages]
        children: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for m in group:
            cid = self._extract_causation_id(m)
            if cid:
                children[cid].append(m)

        if not recursive:
            direct = children.get(mid, [])
            direct.sort(key=lambda m: m.get("global_position", 0))
            return [Message.deserialize(m) for m in direct]

        # BFS for full subtree
        result: list[dict[str, Any]] = []
        queue: deque[str] = deque([mid])
        visited: set[str] = {mid}

        while queue:
            current = queue.popleft()
            for child in children.get(current, []):
                child_id = self._extract_message_id(child)
                if child_id and child_id not in visited:
                    visited.add(child_id)
                    result.append(child)
                    queue.append(child_id)

        result.sort(key=lambda m: m.get("global_position", 0))
        return [Message.deserialize(m) for m in result]

    def build_causation_tree(self, correlation_id: str) -> CausationNode | None:
        """Build a full causation tree for a correlation ID.

        Returns the root node of the tree with children recursively populated.

        Args:
            correlation_id: The correlation ID to trace.

        Returns:
            Root [`CausationNode`][protean.port.event_store.CausationNode] with children, or ``None`` if no
            messages found.
        """
        group = self._load_correlation_group(correlation_id)
        if not group:
            return None

        # Build index and children map
        by_id: dict[str, dict[str, Any]] = {}
        children_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        roots: list[dict[str, Any]] = []

        for m in group:
            hid = self._extract_message_id(m)
            if hid:
                by_id[hid] = m
            cid = self._extract_causation_id(m)
            if cid:
                children_map[cid].append(m)
            else:
                roots.append(m)

        # Sort children by global_position for deterministic ordering
        for cid in children_map:
            children_map[cid].sort(key=lambda m: m.get("global_position", 0))

        visited: set[str] = set()

        def _build_node(raw_msg: dict[str, Any]) -> CausationNode:
            hid = self._extract_message_id(raw_msg) or "?"
            visited.add(hid)

            metadata = raw_msg.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            headers = metadata.get("headers", {})
            if not isinstance(headers, dict):
                headers = {}
            domain_meta = metadata.get("domain", {})
            if not isinstance(domain_meta, dict):
                domain_meta = {}

            node = CausationNode(
                message_id=hid,
                message_type=raw_msg.get("type", headers.get("type", "?")),
                kind=domain_meta.get("kind", "?"),
                stream=raw_msg.get("stream_name", headers.get("stream", "?")),
                time=str(raw_msg.get("time", "")) if raw_msg.get("time") else None,
                global_position=raw_msg.get("global_position"),
            )

            for child_msg in children_map.get(hid, []):
                child_id = self._extract_message_id(child_msg)
                if child_id and child_id not in visited:
                    node.children.append(_build_node(child_msg))

            return node

        if not roots:
            # All messages have causation_id set — pick the one whose
            # causation_id points outside the group
            root_candidates = [
                m for m in group if self._extract_causation_id(m) not in by_id
            ]
            roots = root_candidates if root_candidates else [group[0]]

        roots.sort(key=lambda m: m.get("global_position", 0))
        return _build_node(roots[0])

    @abstractmethod
    def _stream_head_position(self, stream_category: str) -> int:
        """Return the global_position of the newest message in a category stream.

        Used by subscription lag monitoring to determine how far behind
        a subscription is from the head of its stream.

        Args:
            stream_category: The stream category to check (e.g. ``test::user``
                or ``$all``).

        Returns:
            The ``global_position`` of the latest message, or ``-1`` if the
            stream has no messages.
        """

    def stream_head_position(self, stream_category: str) -> int:
        """Return the global_position of the newest message in a category stream.

        Public wrapper around `_stream_head_position`.

        Args:
            stream_category: The stream category to check.

        Returns:
            The ``global_position`` of the latest message, or ``-1`` if the
            stream has no messages.
        """
        return self._stream_head_position(stream_category)

    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------

    # Stable machine tokens for the ``kind`` of an IntegrityViolation. They are
    # part of the ``protean eventstore verify --json`` contract, so treat them as
    # public constants, not free-form strings.
    VERIFY_DUPLICATE_MESSAGE_ID = "duplicate_message_id"
    VERIFY_POSITION_GAP = "position_gap"
    VERIFY_NON_MONOTONIC_GLOBAL_POSITION = "non_monotonic_global_position"
    VERIFY_SNAPSHOT_AHEAD_OF_STREAM = "snapshot_ahead_of_stream"
    VERIFY_MALFORMED_MESSAGE = "malformed_message"
    VERIFY_MALFORMED_SNAPSHOT = "malformed_snapshot"

    _SNAPSHOT_MARKER = ":snapshot-"

    # Fields a message read from ``$all`` must carry; a missing one is a
    # malformed row. ``global_position`` is not here: the ``$all`` read filters
    # ``>= position`` and both adapters make it NOT NULL, so a row without one
    # is never returned to check (see ``_iter_all_messages``).
    _REQUIRED_FIELDS = ("id", "stream_name", "position")

    def _iter_all_messages(self, batch_size: int = 1000) -> Iterator[dict[str, Any]]:
        """Yield every raw message in the store, ordered by ``global_position``.

        Pages through ``$all`` so the raw rows are read in bounded batches rather
        than one unbounded slurp. The read contract (ADR-0024) is an inclusive,
        ``global_position``-ordered page, so the next page starts one past the
        last global_position seen; gaps in ``global_position`` are allowed and
        skipped over safely. Both shipped adapters make ``global_position`` NOT
        NULL and their ``$all`` read filters ``>= position``, so a row without a
        ``global_position`` can neither exist nor be returned here.

        One known limit: paging keys on ``global_position``, which is unique in
        both shipped adapters. If a corrupt store held two rows with the *same*
        global_position and that pair straddled an exact batch boundary, the
        second would be skipped. Detecting that needs a stable unique cursor the
        read contract does not offer, so it is left uncaught rather than papered
        over with a dedup that ties break.
        """
        position = 0
        while True:
            batch = self._read("$all", position=position, no_of_messages=batch_size)
            if not batch:
                return
            yield from batch
            if len(batch) < batch_size:
                return
            position = batch[-1]["global_position"] + 1

    def verify(self) -> IntegrityReport:
        """Check the store's internal invariants without mutating anything.

        Reads the whole store once through ``$all`` and reports every violation
        of these invariants:

        - every row carries its required fields (``id``, ``stream_name``,
          ``position``),
        - per-stream ``position`` is gapless from the stream base (0),
        - ``global_position`` is strictly increasing store-wide,
        - message ids are unique,
        - each ``:snapshot-`` stream carries a well-formed snapshot whose
          ``_version`` does not exceed its aggregate stream head.

        A corrupt row is reported, never silently skipped: that is the whole
        point of the check, so a row missing a required field or a snapshot with
        a non-integer ``_version`` becomes a violation rather than a pass. The
        checks that need a value are still guarded so a corrupt row cannot crash
        the scan.

        This asserts the store's *internal* consistency, not a schema version
        (none is stored today). It is read-only: a clean store yields a report
        with no violations (``ok`` is ``True``).
        """
        violations: list[IntegrityViolation] = []

        seen_ids: set[str] = set()
        prev_global_position: int | None = None
        # Per-stream: the last position seen (streams appear in position order
        # within the global_position-ordered scan) and the head (max) position.
        last_position: dict[str, int] = {}
        stream_head: dict[str, int] = {}
        # Per snapshot stream: the ``_version`` of its most recent snapshot.
        snapshot_version: dict[str, int] = {}

        message_count = 0
        for msg in self._iter_all_messages():
            message_count += 1
            stream = msg.get("stream_name")
            position = msg.get("position")
            global_position = msg.get("global_position")
            message_id = msg.get("id")

            # A row missing any required field is itself a corruption. Flag it
            # and move on: the per-invariant checks below need those values, and
            # running them on a half-populated row would either crash or invent a
            # spurious gap.
            missing = [f for f in self._REQUIRED_FIELDS if msg.get(f) is None]
            if missing:
                violations.append(
                    IntegrityViolation(
                        kind=self.VERIFY_MALFORMED_MESSAGE,
                        stream=stream,
                        position=position,
                        detail=(
                            "Message is missing required field(s): "
                            f"{', '.join(missing)}."
                        ),
                    )
                )
                continue

            # Past the guard the three required fields are present, and a row
            # read from ``$all`` always carries a ``global_position`` (the read
            # filters ``>= position``). Narrow all four for the checks below
            # (the raw dict values are ``Any | None``).
            assert (
                message_id is not None
                and stream is not None
                and position is not None
                and global_position is not None
            )

            # Duplicate message id (the store's own message identity)
            if message_id in seen_ids:
                violations.append(
                    IntegrityViolation(
                        kind=self.VERIFY_DUPLICATE_MESSAGE_ID,
                        stream=stream,
                        position=position,
                        detail=f"Message id '{message_id}' appears more than once.",
                    )
                )
            seen_ids.add(message_id)

            # Strictly increasing global_position store-wide
            if (
                prev_global_position is not None
                and global_position <= prev_global_position
            ):
                violations.append(
                    IntegrityViolation(
                        kind=self.VERIFY_NON_MONOTONIC_GLOBAL_POSITION,
                        stream=stream,
                        position=position,
                        detail=(
                            f"global_position {global_position} does not exceed "
                            f"the previous {prev_global_position}."
                        ),
                    )
                )
            prev_global_position = global_position

            # Per-stream gapless position from base 0
            expected = last_position.get(stream, -1) + 1
            if position != expected:
                violations.append(
                    IntegrityViolation(
                        kind=self.VERIFY_POSITION_GAP,
                        stream=stream,
                        position=position,
                        detail=(
                            f"Stream '{stream}' jumps to position {position}; "
                            f"expected {expected}."
                        ),
                    )
                )
            last_position[stream] = position
            stream_head[stream] = max(stream_head.get(stream, -1), position)

            # Track the latest snapshot version per snapshot stream. A snapshot
            # whose data is not a dict, or whose ``_version`` is missing or not a
            # plain int (``bool`` is an int subclass, so exclude it), is corrupt:
            # flag it here rather than silently dropping it from the head check.
            if self._SNAPSHOT_MARKER in stream:
                data = msg.get("data")
                version = data.get("_version") if isinstance(data, dict) else None
                if isinstance(version, int) and not isinstance(version, bool):
                    snapshot_version[stream] = version
                else:
                    violations.append(
                        IntegrityViolation(
                            kind=self.VERIFY_MALFORMED_SNAPSHOT,
                            stream=stream,
                            position=position,
                            detail=(
                                "Snapshot data is not a dict or its _version is "
                                "not an integer."
                            ),
                        )
                    )

        # Each snapshot's _version must not exceed its aggregate stream head
        for snap_stream, version in snapshot_version.items():
            category, _, identifier = snap_stream.partition(self._SNAPSHOT_MARKER)
            aggregate_stream = f"{category}-{identifier}"
            head = stream_head.get(aggregate_stream, -1)
            if version > head:
                violations.append(
                    IntegrityViolation(
                        kind=self.VERIFY_SNAPSHOT_AHEAD_OF_STREAM,
                        stream=snap_stream,
                        position=None,
                        detail=(
                            f"Snapshot _version {version} exceeds the head position "
                            f"{head} of aggregate stream '{aggregate_stream}'."
                        ),
                    )
                )

        return IntegrityReport(
            message_count=message_count,
            stream_count=len(stream_head),
            violations=violations,
        )

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all events.

        Useful for running tests with a clean slate.
        """

    def _last_event_of_type(
        self, event_cls: type[BaseEvent], stream_category: str | None = None
    ) -> BaseEvent | BaseCommand | None:
        stream_category = stream_category or "$all"
        events = [
            event
            for event in self._read(stream_category)
            if event["type"] == event_cls.__type__
        ]

        return (
            Message.deserialize(events[-1]).to_domain_object()
            if len(events) > 0
            else None
        )

    def _events_of_type(
        self, event_cls: type[BaseEvent], stream_category: str | None = None
    ) -> list[BaseEvent | BaseCommand]:
        """Read events of a specific type in a given stream.

        This is a utility method, especially useful for testing purposes, that retrieves events of a
        specific type from the event store.

        If no stream is specified, events of the requested type will be retrieved from all streams.

        :param event_cls: Class of the event type to be retrieved. Subclass of `BaseEvent`.
        :param stream_category: Stream from which events are to be retrieved. String, optional, default is `None`
        :return: A list of events of `event_cls` type
        """
        stream_category = stream_category or "$all"
        return [
            Message.deserialize(event).to_domain_object()
            for event in self._read(stream_category)
            if event["type"] == event_cls.__type__
        ]
