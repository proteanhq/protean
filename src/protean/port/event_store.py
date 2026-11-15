from __future__ import annotations

from abc import abstractmethod
from collections import defaultdict, deque
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from datetime import datetime
from enum import Flag, auto
from typing import TYPE_CHECKING, Any, Protocol, TypedDict

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.port.health import PoolStats

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.utils.eventing import Message

# Snapshot rows are written with ``message_type="SNAPSHOT"`` and no metadata
# (see ``EventStore._load_aggregate_current`` and ``EventStore.create_snapshot``
# in ``protean.infra.event_store``). They hold an
# aggregate's serialized state, not an event or command, so the read layer
# skips them: ``Message.deserialize`` would raise on their ``None`` metadata,
# and callers of ``read``/``read_all`` expect events and commands only.
SNAPSHOT_TYPE = "SNAPSHOT"


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
    violations: tuple[IntegrityViolation, ...] = ()

    def __post_init__(self) -> None:
        # Accept any iterable at construction but store a tuple, so a caller
        # cannot ``append`` to a report after the fact. ``frozen=True`` seals the
        # attributes; this seals the collection they point at.
        if not isinstance(self.violations, tuple):
            object.__setattr__(self, "violations", tuple(self.violations))

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


class EventStoreCapabilities(Flag):
    """The guarantees an event store makes.

    Each event store declares its flags on ``capabilities``. Check a guarantee
    with ``EventStoreCapabilities.DURABLE in store.capabilities``.
    """

    WRITE = auto()  # Append a message and return its stream position
    READ_STREAM = auto()  # Read one stream by stream position
    READ_CATEGORY = auto()  # Read a category by global position, inclusive
    READ_ALL = auto()  # Read the whole store by global position, inclusive
    EXPECTED_VERSION = auto()  # A stale expected version raises and writes nothing
    CATEGORY_COMMIT_ORDER = auto()  # Category writes become visible in position order
    CONSUMER_GROUPS = auto()  # A category read can be split across group members
    DURABLE = auto()  # Messages survive a process restart
    SCHEMA_MANAGEMENT = auto()  # The store creates and drops its own tables

    # Convenience Capability Sets
    BASIC = WRITE | READ_STREAM | READ_CATEGORY | READ_ALL

    CONSISTENT = BASIC | EXPECTED_VERSION | CATEGORY_COMMIT_ORDER

    PRODUCTION = CONSISTENT | DURABLE


class RawMessage(TypedDict):
    """One row as an event store returns it.

    ``position`` is the row's place in its stream, from 0 with no gaps.
    ``global_position`` is its place in the whole store and may have gaps. A
    snapshot row has ``type == "SNAPSHOT"`` and ``metadata`` of ``None``.
    """

    id: str
    stream_name: str
    type: str
    position: int
    global_position: int
    data: dict[str, Any] | None
    metadata: dict[str, Any] | None
    time: datetime


def row_data(row: RawMessage) -> dict[str, Any]:
    """Return the row's ``data``, or an empty dict when the row has none."""
    return row["data"] or {}


@dataclass(frozen=True)
class EventStoreHealth:
    """The health of an event store.

    ``reachable`` is the result of ``ping()``. ``pool`` describes the
    adapter's connection pool, or is ``None`` for an adapter without one or
    whose pool does not exist yet.
    """

    reachable: bool
    pool: PoolStats | None


class EventStorePort(Protocol):
    """The operations an event-store adapter implements.

    Every read includes the row at ``position``. A stream read pages by the
    stream ``position``. A category read and an all read page by
    ``global_position`` (ADR-0024). A category read returns only streams whose
    category equals ``category`` exactly, and never a snapshot stream
    (``<category>:snapshot-<id>``).
    """

    name: str

    def __init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None:
        """Build the adapter named ``name`` for ``domain`` from ``config``."""

    @property
    @abstractmethod
    def capabilities(self) -> EventStoreCapabilities:
        """The guarantees this event store makes."""

    @abstractmethod
    def write_message(
        self,
        stream_name: str,
        message_type: str,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> int:
        """Append a message to ``stream_name`` and return its stream position.

        Raises:
            ExpectedVersionError: When ``expected_version`` is given and is not
                the stream's current version. Nothing is written.
        """

    @abstractmethod
    def get_stream_messages(
        self, stream_name: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        """Return up to ``limit`` rows of one stream from stream ``position``."""

    @abstractmethod
    def get_category_messages(
        self,
        category: str,
        position: int = 0,
        limit: int = 1000,
        *,
        consumer_group_member: int | None = None,
        consumer_group_size: int | None = None,
    ) -> list[RawMessage]:
        """Return up to ``limit`` rows of ``category`` from ``global_position``.

        With ``consumer_group_member`` and ``consumer_group_size``, return only
        the streams that belong to that member of the group.

        Raises:
            NotSupportedError: When a consumer-group argument is given and the
                adapter does not declare ``CONSUMER_GROUPS``.
            ValueError: When an adapter that declares ``CONSUMER_GROUPS``
                gets only one of the two consumer-group arguments.
        """

    @abstractmethod
    def get_all_messages(
        self, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        """Return up to ``limit`` rows of the whole store from ``global_position``."""

    @abstractmethod
    def get_last_stream_message(self, stream_name: str) -> RawMessage | None:
        """Return the newest row of one stream, or ``None`` when it is empty."""

    @abstractmethod
    def get_last_category_message(self, category: str) -> RawMessage | None:
        """Return the row of ``category`` with the highest ``global_position``.

        Returns ``None`` when the category is empty.
        """

    @abstractmethod
    def get_last_message(self) -> RawMessage | None:
        """Return the row with the highest ``global_position`` in the store.

        Returns ``None`` when the store is empty.
        """

    @abstractmethod
    def stream_ids(self, category: str) -> list[str]:
        """Return the sorted, unique identifiers of the streams in ``category``.

        A stream ``<category>-<id>`` gives ``<id>``. Snapshot streams are left
        out.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Return whether the store answers. Never raises."""

    @abstractmethod
    def health(self) -> EventStoreHealth:
        """Return the store's health record."""

    @abstractmethod
    def get_connection(self) -> object:
        """Return the native client, or ``None`` for an adapter without one."""

    @abstractmethod
    def clear(self) -> None:
        """Delete every message. Test-harness use only."""

    def close(self) -> None:
        """Release the store's connections. The default does nothing."""
        return

    def create_schema(self) -> None:
        """Create the store's tables, behind ``SCHEMA_MANAGEMENT``.

        The default does nothing.
        """
        return

    def drop_schema(self) -> None:
        """Drop the store's tables, behind ``SCHEMA_MANAGEMENT``.

        The default does nothing.
        """
        return


class BaseEventStore(EventStorePort):
    """The base class of every event-store adapter.

    Each adapter subclasses it and implements the `EventStorePort` members.
    Its `read`, `read_all`, `read_last_message`, `stream_head_position`,
    `append`, `load_aggregate`, `create_snapshot` and `create_snapshots` call
    the domain's `EventStore` service, so they act on the domain's adapter,
    `self.domain.event_store._adapter`, not on this instance. The causation
    tracing methods and `verify` still read this instance.
    """

    def __init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        self.config = config

    # ------------------------------------------------------------------
    # Delegates to the domain's `EventStore` service
    # ------------------------------------------------------------------

    def _read_raw(
        self, stream: str, position: int = 0, limit: int = 1000
    ) -> list[RawMessage]:
        return self.domain.event_store._read_raw(stream, position, limit)

    def _read_last_raw(self, stream: str) -> RawMessage | None:
        return self.domain.event_store._read_last_raw(stream)

    def category(self, stream: str) -> str:
        return self.domain.event_store.category(stream)

    def read(self, stream: str, position: int = 0, limit: int = 1000) -> list[Message]:
        return self.domain.event_store.read(stream, position, limit)

    def _read_with_snapshot_positions(
        self, stream: str, position: int = 0, limit: int = 1000
    ) -> tuple[list[Message], list[int]]:
        return self.domain.event_store._read_with_snapshot_positions(
            stream, position, limit
        )

    def read_all(
        self, stream: str = "$all", *, page_size: int = 1000
    ) -> Iterator[Message]:
        return self.domain.event_store.read_all(stream, page_size=page_size)

    def _read_all_raw(
        self, stream: str = "$all", *, page_size: int = 1000
    ) -> Iterator[RawMessage]:
        return self.domain.event_store._read_all_raw(stream, page_size=page_size)

    def read_last_message(self, stream: str) -> Message | None:
        return self.domain.event_store.read_last_message(stream)

    def stream_head_position(self, stream_category: str) -> int:
        return self.domain.event_store.category_head_position(stream_category)

    def append(self, object: BaseEvent | BaseCommand) -> int:
        return self.domain.event_store.append(object)

    def load_aggregate(
        self,
        part_of: type[BaseAggregate],
        identifier: str,
        *,
        at_version: int | None = None,
        as_of: datetime | None = None,
    ) -> BaseAggregate | None:
        return self.domain.event_store.load_aggregate(
            part_of, identifier, at_version=at_version, as_of=as_of
        )

    def _read_stream_fully(
        self,
        stream: str,
        start_position: int = 0,
        max_rows: int | None = None,
        *,
        page_size: int = 1000,
    ) -> deque[RawMessage]:
        return self.domain.event_store._read_stream_fully(
            stream, start_position, max_rows, page_size=page_size
        )

    def create_snapshot(self, part_of: type[BaseAggregate], identifier: str) -> bool:
        return self.domain.event_store.create_snapshot(part_of, identifier)

    def create_snapshots(self, part_of: type[BaseAggregate]) -> int:
        return self.domain.event_store.create_snapshots(part_of)

    # ------------------------------------------------------------------
    # Causation chain traversal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_message_id(msg: Mapping[str, Any]) -> str | None:
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
    def _extract_causation_id(msg: Mapping[str, Any]) -> str | None:
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
    def _extract_correlation_id(msg: Mapping[str, Any]) -> str | None:
        """Extract correlation_id from a raw message dict."""
        metadata = msg.get("metadata")
        if not metadata or not isinstance(metadata, dict):
            return None
        domain = metadata.get("domain")
        if not domain or not isinstance(domain, dict):
            return None
        correlation_id: str | None = domain.get("correlation_id")
        return correlation_id

    def _load_correlation_group(self, correlation_id: str) -> list[RawMessage]:
        """Load all raw messages sharing a correlation_id from the event store.

        Reads ``$all`` and filters by ``correlation_id``.
        This is a debugging/inspection utility, not optimized for high-throughput.
        """
        all_messages = self.get_all_messages(limit=1_000_000)
        return [
            m for m in all_messages if self._extract_correlation_id(m) == correlation_id
        ]

    def _resolve_and_load_group(
        self, message_id: str | Message
    ) -> tuple[str, list[RawMessage]]:
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
            mid, cid = _ids_from_message(message_id)
            if mid is None:
                raise ValueError("Message has no headers.id")
            if cid is None:
                return mid, []
            group = self._load_correlation_group(cid)
            return mid, group

        return message_id, _scan_for_group(self, message_id)

    # ------------------------------------------------------------------
    # Public causation chain API
    # ------------------------------------------------------------------

    def trace_causation(self, message_id: str | Message) -> list[Message]:
        """Return the causation chain from the root message down to ``message_id``.

        Args:
            message_id: A Protean message ID string (``headers.id``) or
                a `Message` object.

        Returns:
            `Message` objects in causal order, root first and the given message
            last.

        Raises:
            ValueError: If the message cannot be found in the event store.
        """
        mid, group = self._resolve_and_load_group(message_id)

        # Build lookup: headers.id -> raw_message
        by_id: dict[str, RawMessage] = {}
        for m in group:
            hid = self._extract_message_id(m)
            if hid:
                by_id[hid] = m

        # Walk up from target to root
        chain: list[RawMessage] = []
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
            ValueError: If the message cannot be found in the event store.
        """
        mid, group = self._resolve_and_load_group(message_id)

        # Build children lookup: causation_id -> [raw_messages]
        children: dict[str, list[RawMessage]] = defaultdict(list)
        for m in group:
            cid = self._extract_causation_id(m)
            if cid:
                children[cid].append(m)

        if not recursive:
            direct = children.get(mid, [])
            direct.sort(key=lambda m: m.get("global_position", 0))
            return [Message.deserialize(m) for m in direct]

        # BFS for full subtree
        result: list[RawMessage] = []
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

        by_id, children_map, roots = _index_group(self, group)
        roots = _pick_roots(self, group, by_id, roots)
        visited: set[str] = set()
        return _causation_node(self, roots[0], children_map, visited)

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

    def _iter_all_messages(self, batch_size: int = 1000) -> Iterator[RawMessage]:
        """Yield every raw row in the store, ordered by ``global_position``.

        Rows come back as stored dicts, not deserialized, so snapshot rows and
        malformed rows reach ``verify`` intact. Reads ``$all`` in pages of
        ``batch_size`` rows.
        """
        position = 0
        while True:
            # Read this adapter, not the domain's: `verify` checks the store it
            # is called on, which a standalone build may not be.
            batch = self.get_all_messages(position=position, limit=batch_size)
            if not batch:
                return
            yield from batch
            if len(batch) < batch_size:
                return
            # Reads are inclusive, so resume one past the last global_position.
            # A corrupt store with two rows sharing a global_position across a
            # page boundary would lose the second; the read contract offers no
            # unique cursor to catch that.
            position = batch[-1]["global_position"] + 1

    def _check_body(
        self,
        msg: Mapping[str, Any],
        stream: str,
        position: int,
        snapshot_version: dict[str, int],
    ) -> IntegrityViolation | None:
        """Check one well-formed row's ``data`` and return its violation, if any.

        A snapshot row with a valid ``_version`` records it in
        ``snapshot_version`` for the head check.
        """
        data = msg.get("data")
        # Track the latest snapshot version per snapshot stream. A snapshot
        # whose data is not a dict, or whose ``_version`` is missing or not a
        # plain int (``bool`` is an int subclass, so exclude it), is corrupt:
        # flag it here rather than silently dropping it from the head check.
        if self._SNAPSHOT_MARKER in stream:
            version = data.get("_version") if isinstance(data, dict) else None
            if isinstance(version, int) and not isinstance(version, bool):
                snapshot_version[stream] = version
                return None
            return IntegrityViolation(
                kind=self.VERIFY_MALFORMED_SNAPSHOT,
                stream=stream,
                position=position,
                detail="Snapshot data is not a dict or its _version is not an integer.",
            )
        # An empty dict is a valid body. Message DB's ``data`` column is
        # ``jsonb``, so it can also hold an array, string or number, which no
        # reader can turn into a message.
        if isinstance(data, dict):
            return None
        detail = (
            "Message data is NULL."
            if data is None
            else f"Message data is a {type(data).__name__}, not an object."
        )
        return IntegrityViolation(
            kind=self.VERIFY_MALFORMED_MESSAGE,
            stream=stream,
            position=position,
            detail=detail,
        )

    def verify(self) -> IntegrityReport:
        """Check the store's internal invariants and report every violation.

        Reads the whole store through ``$all`` and changes nothing. It checks
        that:

        - every row carries ``id``, ``stream_name`` and ``position``,
        - each stream's ``position`` runs from 0 with no gaps,
        - ``global_position`` strictly increases across the store,
        - message ids are unique,
        - every row outside a ``:snapshot-`` stream has a body that is an
          object (``data`` is a dict, not NULL, an array or a scalar),
        - each ``:snapshot-`` stream holds a well-formed snapshot whose
          ``_version`` is not past the head of its aggregate stream.

        A corrupt row, such as one missing a required field, a message with a
        NULL or non-object body or a snapshot with a non-integer ``_version``,
        is reported as a violation and never skipped. A NULL or non-object body
        is reported as ``malformed_message`` and still counts as its stream's
        position.

        Returns:
            An `IntegrityReport` of the violations found. ``ok`` is ``True``
            when there are none.
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
        # Scan raw rows: ``read_all`` leaves out snapshot rows and raises on
        # malformed rows, and this check must inspect both.
        for msg in self._iter_all_messages():
            message_count += 1
            stream = msg.get("stream_name")
            position = msg.get("position")
            global_position = msg.get("global_position")
            message_id = msg.get("id")

            # A row read from ``$all`` always carries a ``global_position`` (the
            # read filters ``>= position``), so check monotonicity FIRST, before
            # the malformed guard can ``continue``. A row can be malformed and
            # break monotonicity at once, and verify reports every violation.
            assert global_position is not None  # read-contract guarantee (mypy)
            violation = _global_order_violation(
                self, stream, position, global_position, prev_global_position
            )
            if violation is not None:
                violations.append(violation)
            prev_global_position = global_position

            # A row missing any required field is itself a corruption. Flag it
            # and move on: the remaining checks need those values, and running
            # them on a half-populated row would either crash or invent a
            # spurious gap.
            violation = _missing_fields_violation(self, msg, stream, position)
            if violation is not None:
                violations.append(violation)
                continue

            # Past the guard the three required fields are present. Narrow them
            # for the checks below (the raw dict values are ``Any | None``).
            assert (
                message_id is not None and stream is not None and position is not None
            )

            violations.extend(
                _identity_and_position_violations(
                    self,
                    message_id,
                    stream,
                    position,
                    seen_ids,
                    last_position,
                    stream_head,
                )
            )

            violation = self._check_body(msg, stream, position, snapshot_version)
            if violation is not None:
                violations.append(violation)

        violations.extend(_snapshot_violations(self, snapshot_version, stream_head))

        return IntegrityReport(
            message_count=message_count,
            stream_count=len(stream_head),
            violations=tuple(violations),
        )


def _ids_from_message(message: Message) -> tuple[str | None, str | None]:
    """Return the message's ``headers.id`` and ``correlation_id``."""
    mid = (
        message.metadata.headers.id
        if message.metadata and message.metadata.headers
        else None
    )
    cid = (
        message.metadata.domain.correlation_id
        if message.metadata and message.metadata.domain
        else None
    )
    return mid, cid


def _scan_for_group(store: BaseEventStore, message_id: str) -> list[RawMessage]:
    """Return the correlation group of the message with ID ``message_id``.

    Raises:
        ValueError: No message in the store has that ID.
    """
    # String ID: single pass to find the target and its group
    all_messages = store.get_all_messages(limit=1_000_000)
    target_correlation_id: str | None = None
    for m in all_messages:
        if store._extract_message_id(m) == message_id:
            target_correlation_id = store._extract_correlation_id(m)
            break

    if target_correlation_id is None:
        raise ValueError(f"Message with ID '{message_id}' not found in event store")

    return [
        m
        for m in all_messages
        if store._extract_correlation_id(m) == target_correlation_id
    ]


def _index_group(
    store: BaseEventStore, group: list[RawMessage]
) -> tuple[
    dict[str, RawMessage],
    dict[str, list[RawMessage]],
    list[RawMessage],
]:
    """Index a correlation group for the causation tree.

    Returns the messages by ``headers.id``, the children of each message by
    its ID sorted by ``global_position``, and the messages with no
    causation ID.
    """
    by_id: dict[str, RawMessage] = {}
    children_map: dict[str, list[RawMessage]] = defaultdict(list)
    roots: list[RawMessage] = []

    for m in group:
        hid = store._extract_message_id(m)
        if hid:
            by_id[hid] = m
        cid = store._extract_causation_id(m)
        if cid:
            children_map[cid].append(m)
        else:
            roots.append(m)

    # Sort children by global_position for deterministic ordering
    for children in children_map.values():
        children.sort(key=lambda m: m.get("global_position", 0))

    return by_id, children_map, roots


def _pick_roots(
    store: BaseEventStore,
    group: list[RawMessage],
    by_id: dict[str, RawMessage],
    roots: list[RawMessage],
) -> list[RawMessage]:
    """Return the root candidates of the causation tree, sorted by
    ``global_position``. The list is never empty for a non-empty group."""
    if not roots:
        # All messages have causation_id set: pick the one whose
        # causation_id points outside the group
        root_candidates = [
            m for m in group if store._extract_causation_id(m) not in by_id
        ]
        roots = root_candidates if root_candidates else [group[0]]

    roots.sort(key=lambda m: m.get("global_position", 0))
    return roots


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _causation_node(
    store: BaseEventStore,
    raw_msg: RawMessage,
    children_map: dict[str, list[RawMessage]],
    visited: set[str],
) -> CausationNode:
    """Build the node for ``raw_msg`` and, recursively, its unvisited children.

    Adds each built message's ID to ``visited``.
    """
    hid = store._extract_message_id(raw_msg) or "?"
    visited.add(hid)

    metadata = _dict_or_empty(raw_msg.get("metadata", {}))
    headers = _dict_or_empty(metadata.get("headers", {}))
    domain_meta = _dict_or_empty(metadata.get("domain", {}))

    node = CausationNode(
        message_id=hid,
        message_type=raw_msg.get("type", headers.get("type", "?")),
        kind=domain_meta.get("kind", "?"),
        stream=raw_msg.get("stream_name", headers.get("stream", "?")),
        time=str(raw_msg.get("time", "")) if raw_msg.get("time") else None,
        global_position=raw_msg.get("global_position"),
    )

    for child_msg in children_map.get(hid, []):
        child_id = store._extract_message_id(child_msg)
        if child_id and child_id not in visited:
            node.children.append(
                _causation_node(store, child_msg, children_map, visited)
            )

    return node


def _global_order_violation(
    store: BaseEventStore,
    stream: Any,
    position: Any,
    global_position: int,
    prev_global_position: int | None,
) -> IntegrityViolation | None:
    """Return a violation when ``global_position`` does not exceed the
    previous row's."""
    if prev_global_position is not None and global_position <= prev_global_position:
        return IntegrityViolation(
            kind=store.VERIFY_NON_MONOTONIC_GLOBAL_POSITION,
            stream=stream,
            position=position,
            detail=(
                f"global_position {global_position} does not exceed "
                f"the previous {prev_global_position}."
            ),
        )
    return None


def _missing_fields_violation(
    store: BaseEventStore, msg: Mapping[str, Any], stream: Any, position: Any
) -> IntegrityViolation | None:
    """Return a violation when ``msg`` lacks a required field."""
    # Only absence is checked: every adapter types these columns, so a
    # required field that is present never has the wrong type. ``data`` is
    # not required here: Message DB allows a NULL body, and the row still
    # holds its position, so ``verify`` checks it separately, after the
    # position bookkeeping.
    missing = [f for f in store._REQUIRED_FIELDS if msg.get(f) is None]
    if not missing:
        return None
    return IntegrityViolation(
        kind=store.VERIFY_MALFORMED_MESSAGE,
        stream=stream,
        position=position,
        detail=f"Message is missing required field(s): {', '.join(missing)}.",
    )


def _identity_and_position_violations(
    store: BaseEventStore,
    message_id: str,
    stream: str,
    position: int,
    seen_ids: set[str],
    last_position: dict[str, int],
    stream_head: dict[str, int],
) -> list[IntegrityViolation]:
    """Check a row's message ID and stream position, and record both.

    Returns a duplicate-ID violation before a position-gap violation.
    """
    violations: list[IntegrityViolation] = []

    # Duplicate message id (the store's own message identity)
    if message_id in seen_ids:
        violations.append(
            IntegrityViolation(
                kind=store.VERIFY_DUPLICATE_MESSAGE_ID,
                stream=stream,
                position=position,
                detail=f"Message id '{message_id}' appears more than once.",
            )
        )
    seen_ids.add(message_id)

    # Per-stream gapless position from base 0
    expected = last_position.get(stream, -1) + 1
    if position != expected:
        violations.append(
            IntegrityViolation(
                kind=store.VERIFY_POSITION_GAP,
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

    return violations


def _snapshot_violations(
    store: BaseEventStore,
    snapshot_version: dict[str, int],
    stream_head: dict[str, int],
) -> list[IntegrityViolation]:
    """Return a violation for each snapshot whose ``_version`` is past the
    head of its aggregate stream."""
    violations: list[IntegrityViolation] = []
    # Each snapshot's _version must not exceed its aggregate stream head
    for snap_stream, version in snapshot_version.items():
        category, _, identifier = snap_stream.partition(store._SNAPSHOT_MARKER)
        aggregate_stream = f"{category}-{identifier}"
        head = stream_head.get(aggregate_stream, -1)
        if version > head:
            violations.append(
                IntegrityViolation(
                    kind=store.VERIFY_SNAPSHOT_AHEAD_OF_STREAM,
                    stream=snap_stream,
                    position=None,
                    detail=(
                        f"Snapshot _version {version} exceeds the head position "
                        f"{head} of aggregate stream '{aggregate_stream}'."
                    ),
                )
            )
    return violations
