"""The event store's integrity check.

`verify` reads every row of a store through its `EventStorePort` members and
reports each row that breaks one of the store's internal invariants. It
changes nothing. ``protean eventstore verify`` prints its report.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from protean.port.event_store import EventStorePort, RawMessage


class ViolationKind(StrEnum):
    """The kind of an [`IntegrityViolation`][protean.infra.integrity.IntegrityViolation].

    Each value is a stable machine token in the ``protean eventstore verify
    --json`` output.
    """

    DUPLICATE_MESSAGE_ID = "duplicate_message_id"
    POSITION_GAP = "position_gap"
    NON_MONOTONIC_GLOBAL_POSITION = "non_monotonic_global_position"
    SNAPSHOT_AHEAD_OF_STREAM = "snapshot_ahead_of_stream"
    MALFORMED_MESSAGE = "malformed_message"
    MALFORMED_SNAPSHOT = "malformed_snapshot"


@dataclass(frozen=True)
class IntegrityViolation:
    """A single violation of the event store's internal invariants.

    ``kind`` names the invariant that broke; ``stream`` and ``position`` name
    where the violation was found (either may be ``None`` when it is not
    stream- or position-specific); ``detail`` is a human-readable explanation.
    """

    kind: ViolationKind
    stream: str | None
    position: int | None
    detail: str


@dataclass(frozen=True)
class IntegrityReport:
    """The result of [`verify`][protean.infra.event_store.EventStore.verify].

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


_SNAPSHOT_MARKER = ":snapshot-"

# Fields a message read from ``$all`` must carry; a missing one is a
# malformed row. ``global_position`` is not here: the ``$all`` read filters
# ``>= position`` and both adapters make it NOT NULL, so a row without one
# is never returned to check (see ``_iter_all_messages``).
_REQUIRED_FIELDS = ("id", "stream_name", "position")


def _iter_all_messages(
    adapter: EventStorePort, batch_size: int = 1000
) -> Iterator[RawMessage]:
    """Yield every raw row in the store, ordered by ``global_position``.

    Rows come back as stored dicts, not deserialized, so snapshot rows and
    malformed rows reach ``verify`` intact. Reads ``$all`` in pages of
    ``batch_size`` rows.
    """
    position = 0
    while True:
        batch = adapter.get_all_messages(position=position, limit=batch_size)
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
    if _SNAPSHOT_MARKER in stream:
        version = data.get("_version") if isinstance(data, dict) else None
        if isinstance(version, int) and not isinstance(version, bool):
            snapshot_version[stream] = version
            return None
        return IntegrityViolation(
            kind=ViolationKind.MALFORMED_SNAPSHOT,
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
        kind=ViolationKind.MALFORMED_MESSAGE,
        stream=stream,
        position=position,
        detail=detail,
    )


def verify(adapter: EventStorePort) -> IntegrityReport:
    """Check the store's internal invariants and report every violation.

    Reads the whole store through ``$all``, then reads the snapshot of each
    stream with a ``-`` in its name, other than ``:snapshot-`` streams,
    whose snapshot ``$all`` did not return. It changes
    nothing. It checks that:

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

    Args:
        adapter: The event store to check.

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
    for msg in _iter_all_messages(adapter):
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
            stream, position, global_position, prev_global_position
        )
        if violation is not None:
            violations.append(violation)
        prev_global_position = global_position

        # A row missing any required field is itself a corruption. Flag it
        # and move on: the remaining checks need those values, and running
        # them on a half-populated row would either crash or invent a
        # spurious gap.
        violation = _missing_fields_violation(msg, stream, position)
        if violation is not None:
            violations.append(violation)
            continue

        # Past the guard the three required fields are present. Narrow them
        # for the checks below (the raw dict values are ``Any | None``).
        assert message_id is not None and stream is not None and position is not None

        violations.extend(
            _identity_and_position_violations(
                message_id,
                stream,
                position,
                seen_ids,
                last_position,
                stream_head,
            )
        )

        violation = _check_body(msg, stream, position, snapshot_version)
        if violation is not None:
            violations.append(violation)

    violations.extend(
        _unscanned_snapshot_violations(adapter, stream_head, snapshot_version, seen_ids)
    )
    violations.extend(_snapshot_violations(snapshot_version, stream_head))

    return IntegrityReport(
        message_count=message_count,
        stream_count=len(stream_head),
        violations=tuple(violations),
    )


def _global_order_violation(
    stream: Any,
    position: Any,
    global_position: int,
    prev_global_position: int | None,
) -> IntegrityViolation | None:
    """Return a violation when ``global_position`` does not exceed the
    previous row's."""
    if prev_global_position is not None and global_position <= prev_global_position:
        return IntegrityViolation(
            kind=ViolationKind.NON_MONOTONIC_GLOBAL_POSITION,
            stream=stream,
            position=position,
            detail=(
                f"global_position {global_position} does not exceed "
                f"the previous {prev_global_position}."
            ),
        )
    return None


def _missing_fields_violation(
    msg: Mapping[str, Any], stream: Any, position: Any
) -> IntegrityViolation | None:
    """Return a violation when ``msg`` lacks a required field."""
    # Only absence is checked: every adapter types these columns, so a
    # required field that is present never has the wrong type. ``data`` is
    # not required here: Message DB allows a NULL body, and the row still
    # holds its position, so ``verify`` checks it separately, after the
    # position bookkeeping.
    missing = [f for f in _REQUIRED_FIELDS if msg.get(f) is None]
    if not missing:
        return None
    return IntegrityViolation(
        kind=ViolationKind.MALFORMED_MESSAGE,
        stream=stream,
        position=position,
        detail=f"Message is missing required field(s): {', '.join(missing)}.",
    )


def _identity_and_position_violations(
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

    violation = _duplicate_id_violation(message_id, stream, position, seen_ids)
    if violation is not None:
        violations.append(violation)

    # Per-stream gapless position from base 0
    expected = last_position.get(stream, -1) + 1
    if position != expected:
        violations.append(
            IntegrityViolation(
                kind=ViolationKind.POSITION_GAP,
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


def _duplicate_id_violation(
    message_id: str, stream: str, position: int, seen_ids: set[str]
) -> IntegrityViolation | None:
    """Return a violation when ``message_id`` is in ``seen_ids``, and record it."""
    duplicate = message_id in seen_ids
    seen_ids.add(message_id)
    if not duplicate:
        return None
    return IntegrityViolation(
        kind=ViolationKind.DUPLICATE_MESSAGE_ID,
        stream=stream,
        position=position,
        detail=f"Message id '{message_id}' appears more than once.",
    )


def _unscanned_snapshot_violations(
    adapter: EventStorePort,
    stream_head: dict[str, int],
    snapshot_version: dict[str, int],
    seen_ids: set[str],
) -> list[IntegrityViolation]:
    """Check the snapshot of each stream the scan saw without one.

    Streams with no ``-`` in their name and ``:snapshot-`` streams are
    skipped.

    A store that keeps snapshots apart from its events, such as the sql event
    store, leaves them out of ``$all``. A well-formed snapshot read here is
    recorded in ``snapshot_version`` for the head check.
    """
    violations: list[IntegrityViolation] = []
    for stream in list(stream_head):
        category, dash, identifier = stream.partition("-")
        if _SNAPSHOT_MARKER in stream or not dash:
            continue
        snapshot_stream = f"{category}{_SNAPSHOT_MARKER}{identifier}"
        if snapshot_stream in stream_head:
            continue
        row = adapter.get_last_stream_message(snapshot_stream)
        if row is None:
            continue
        violation = _missing_fields_violation(row, snapshot_stream, row.get("position"))
        if violation is not None:
            violations.append(violation)
            continue
        violation = _duplicate_id_violation(
            row["id"], snapshot_stream, row["position"], seen_ids
        )
        if violation is not None:
            violations.append(violation)
        violation = _check_body(row, snapshot_stream, row["position"], snapshot_version)
        if violation is not None:
            violations.append(violation)
    return violations


def _snapshot_violations(
    snapshot_version: dict[str, int],
    stream_head: dict[str, int],
) -> list[IntegrityViolation]:
    """Return a violation for each snapshot whose ``_version`` is past the
    head of its aggregate stream."""
    violations: list[IntegrityViolation] = []
    # Each snapshot's _version must not exceed its aggregate stream head
    for snap_stream, version in snapshot_version.items():
        category, _, identifier = snap_stream.partition(_SNAPSHOT_MARKER)
        aggregate_stream = f"{category}-{identifier}"
        head = stream_head.get(aggregate_stream, -1)
        if version > head:
            violations.append(
                IntegrityViolation(
                    kind=ViolationKind.SNAPSHOT_AHEAD_OF_STREAM,
                    stream=snap_stream,
                    position=None,
                    detail=(
                        f"Snapshot _version {version} exceeds the head position "
                        f"{head} of aggregate stream '{aggregate_stream}'."
                    ),
                )
            )
    return violations
