"""Tests for ``protean.infra.integrity.verify``.

``verify`` reads the whole store through the adapter's ``$all`` read, so its
logic is identical for every adapter. These tests
drive it against a minimal in-file store whose ``$all`` pages over a preloaded
list of raw message dicts. That lets each invariant be violated
deterministically, including corruptions the real adapters do not readily
produce: MessageDB keys both ``id`` and ``global_position`` as unique, and the
memory adapter increments ``global_position`` and mints a fresh uuid4 ``id`` per
write. Those corruptions only arise from an out-of-band restore, which is
exactly what ``verify`` exists to catch.
"""

import json
from typing import Any

import pytest

from protean.infra.integrity import (
    IntegrityReport,
    IntegrityViolation,
    ViolationKind,
    _iter_all_messages,
    verify,
)
from protean.port.event_store import EventStoreCapabilities, EventStorePort


class _ListStore(EventStorePort):
    """An ``EventStorePort`` backed by a preloaded list of raw dicts.

    Only the reads ``verify`` uses are implemented: ``$all`` reads, which page
    by ``global_position`` exactly like the real adapters, so the iterator's
    paging is genuinely exercised, and the last message of a stream.
    """

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        # Store-wide order is by global_position, matching the read contract.
        self._messages = sorted(messages, key=lambda m: m["global_position"])

    @property
    def capabilities(self) -> EventStoreCapabilities:  # pragma: no cover
        return EventStoreCapabilities.BASIC

    def get_all_messages(self, position: int = 0, limit: int = 1000) -> list[Any]:
        page = [m for m in self._messages if m["global_position"] >= position]
        return page[:limit]

    # Unused abstract members: verify never calls them.
    def write_message(self, *args: Any, **kwargs: Any) -> int:  # pragma: no cover
        raise NotImplementedError

    def get_stream_messages(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def get_category_messages(
        self, *args: Any, **kwargs: Any
    ) -> Any:  # pragma: no cover
        raise NotImplementedError

    def get_last_stream_message(
        self, stream_name: str, *args: Any, **kwargs: Any
    ) -> dict[str, Any] | None:
        rows = [m for m in self._messages if m.get("stream_name") == stream_name]
        return rows[-1] if rows else None

    def get_last_category_message(
        self, *args: Any, **kwargs: Any
    ) -> Any:  # pragma: no cover
        raise NotImplementedError

    def get_last_message(self) -> Any:  # pragma: no cover
        raise NotImplementedError

    def stream_ids(self, *args: Any, **kwargs: Any) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def ping(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def health(self) -> Any:  # pragma: no cover
        raise NotImplementedError

    def get_connection(self) -> object:  # pragma: no cover
        raise NotImplementedError

    def clear(self) -> None:  # pragma: no cover
        raise NotImplementedError


# Sentinel so an explicit ``data=None`` (a non-dict corruption) is preserved
# rather than coerced to ``{}``; omitting ``data`` still defaults to ``{}``.
_UNSET = object()


def _msg(
    global_position: int,
    stream_name: str,
    position: int,
    *,
    id: str | None = None,
    data: Any = _UNSET,
) -> dict[str, Any]:
    return {
        "global_position": global_position,
        "stream_name": stream_name,
        "position": position,
        "id": id if id is not None else f"id-{global_position}",
        "type": "Event",
        "data": {} if data is _UNSET else data,
    }


pytestmark = pytest.mark.no_test_domain


def test_clean_store_reports_no_violations():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user-abc", 1),
            _msg(3, "test::user-def", 0),
        ]
    )

    report = verify(store)

    assert report.ok is True
    assert report.violations == ()
    assert report.message_count == 3
    assert report.stream_count == 2


def test_empty_store_is_clean():
    report = verify(_ListStore([]))

    assert report.ok is True
    assert report.message_count == 0
    assert report.stream_count == 0


def test_duplicate_message_id_is_flagged():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0, id="dup"),
            _msg(2, "test::user-abc", 1, id="dup"),
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == ViolationKind.DUPLICATE_MESSAGE_ID
    assert violation.stream == "test::user-abc"
    assert violation.position == 1
    assert "dup" in violation.detail


def test_position_gap_names_stream_and_missing_position():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user-abc", 2),  # skips position 1
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == ViolationKind.POSITION_GAP
    assert violation.stream == "test::user-abc"
    assert violation.position == 2
    assert "expected 1" in violation.detail


def test_position_gap_from_base_is_flagged():
    store = _ListStore([_msg(1, "test::user-abc", 3)])  # first message not at 0

    report = verify(store)

    assert report.ok is False
    assert report.violations[0].kind == ViolationKind.POSITION_GAP
    assert "expected 0" in report.violations[0].detail


def test_non_monotonic_global_position_is_flagged():
    # Two messages share a global_position, so the read returns them adjacent
    # and the second does not exceed the first.
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(1, "test::user-def", 0),
        ]
    )

    report = verify(store)

    assert report.ok is False
    kinds = [v.kind for v in report.violations]
    assert ViolationKind.NON_MONOTONIC_GLOBAL_POSITION in kinds


def test_snapshot_ahead_of_stream_head_is_flagged():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user-abc", 1),
            _msg(3, "test::user:snapshot-abc", 0, data={"_version": 5}),
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == ViolationKind.SNAPSHOT_AHEAD_OF_STREAM
    assert violation.stream == "test::user:snapshot-abc"
    assert violation.position is None
    assert "test::user-abc" in violation.detail


def test_snapshot_at_stream_head_is_clean():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user-abc", 1),
            _msg(3, "test::user:snapshot-abc", 0, data={"_version": 1}),  # == head
        ]
    )

    assert verify(store).ok is True


def test_snapshot_without_aggregate_stream_is_flagged():
    # A snapshot whose aggregate stream has no events at all: head is -1, so any
    # non-negative _version is ahead.
    store = _ListStore([_msg(1, "test::user:snapshot-orphan", 0, data={"_version": 0})])

    report = verify(store)

    assert report.ok is False
    assert report.violations[0].kind == ViolationKind.SNAPSHOT_AHEAD_OF_STREAM


def test_snapshot_with_non_int_version_is_flagged_malformed():
    # A corrupt snapshot whose _version is not an integer is flagged as
    # malformed rather than silently skipped, and does not crash the scan.
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user:snapshot-abc", 0, data={"_version": "oops"}),
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert len(report.violations) == 1
    assert report.violations[0].kind == ViolationKind.MALFORMED_SNAPSHOT
    assert report.violations[0].stream == "test::user:snapshot-abc"


def test_snapshot_with_non_dict_data_is_flagged_malformed():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user:snapshot-abc", 0, data=None),
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert report.violations[0].kind == ViolationKind.MALFORMED_SNAPSHOT


def test_snapshot_with_bool_version_is_flagged_malformed():
    # ``bool`` is an ``int`` subclass; a True/False _version must not slip
    # through the integer guard and be read as version 1/0.
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user:snapshot-abc", 0, data={"_version": True}),
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert report.violations[0].kind == ViolationKind.MALFORMED_SNAPSHOT


def test_most_recent_snapshot_wins_for_head_check():
    # Two snapshot rows in one stream: an earlier one ahead of head, a later one
    # at head. The latest (at-head) is the one compared, so the store is clean.
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user-abc", 1),
            _msg(3, "test::user:snapshot-abc", 0, data={"_version": 9}),  # earlier
            _msg(
                4, "test::user:snapshot-abc", 1, data={"_version": 1}
            ),  # latest, at head
        ]
    )

    assert verify(store).ok is True


def test_latest_snapshot_ahead_is_flagged_even_after_a_clean_earlier_one():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user-abc", 1),
            _msg(
                3, "test::user:snapshot-abc", 0, data={"_version": 1}
            ),  # earlier, at head
            _msg(
                4, "test::user:snapshot-abc", 1, data={"_version": 9}
            ),  # latest, ahead
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert report.violations[0].kind == ViolationKind.SNAPSHOT_AHEAD_OF_STREAM


def test_multiple_violations_accumulate_in_one_report():
    # A single scan must report every violation, not stop at the first, and keep
    # the counts correct across several streams.
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user-abc", 2),  # gap in stream A
            _msg(3, "test::order-xyz", 0, id="dup"),
            _msg(4, "test::order-xyz", 1, id="dup"),  # duplicate id in stream B
            _msg(
                5, "test::user:snapshot-abc", 0, data={"_version": 9}
            ),  # ahead of head (1)
        ]
    )

    report = verify(store)

    assert report.ok is False
    kinds = sorted(v.kind for v in report.violations)
    assert kinds == [
        ViolationKind.DUPLICATE_MESSAGE_ID,
        ViolationKind.POSITION_GAP,
        ViolationKind.SNAPSHOT_AHEAD_OF_STREAM,
    ]
    assert report.message_count == 5
    assert report.stream_count == 3


def test_iterator_pages_across_batches():
    # More messages than one page, all valid: exercises the paging loop and its
    # global_position + 1 advance without dropping or double-counting any.
    messages = [_msg(gp, "test::user-abc", gp - 1) for gp in range(1, 51)]
    store = _ListStore(messages)

    report = verify(store)

    assert report.ok is True
    assert report.message_count == 50

    # Force multiple pages with a tiny batch size and confirm every message is
    # yielded exactly once, in order.
    seen = [m["global_position"] for m in _iter_all_messages(store, batch_size=7)]
    assert seen == list(range(1, 51))


def test_iterator_pages_across_sparse_global_positions():
    # global_position may have gaps (the memory adapter documents this). The
    # cursor advances past the highest gp seen, so a sparse sequence spanning
    # several pages must still yield every message exactly once.
    gps = [1, 8, 9, 40, 41, 300, 301, 999]
    store = _ListStore([_msg(gp, "test::user-abc", i) for i, gp in enumerate(gps)])

    seen = [m["global_position"] for m in _iter_all_messages(store, batch_size=3)]

    assert seen == gps


def test_messages_missing_required_field_are_flagged_malformed():
    # A row missing a required field is a corruption, reported (not skipped) so
    # verify cannot pass a store it could not fully check.
    store = _ListStore(
        [
            {
                "global_position": 1,
                "stream_name": "test::user-abc",
                "id": "a",
            },  # no position
            {"global_position": 2, "position": 1, "id": "b"},  # no stream_name
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert report.message_count == 2
    kinds = [v.kind for v in report.violations]
    assert kinds == [
        ViolationKind.MALFORMED_MESSAGE,
        ViolationKind.MALFORMED_MESSAGE,
    ]
    assert "position" in report.violations[0].detail
    assert "stream_name" in report.violations[1].detail


def test_malformed_row_still_reports_non_monotonic_global_position():
    # A malformed row (missing stream_name) that also duplicates a
    # global_position must report BOTH the missing field and the monotonicity
    # break; global_position is always present, so that check runs first.
    store = _ListStore(
        [
            _msg(2, "test::user-abc", 0),
            {"global_position": 2, "position": 1, "id": "b"},  # missing stream, dup gp
        ]
    )

    report = verify(store)

    assert report.ok is False
    kinds = sorted(v.kind for v in report.violations)
    assert kinds == [
        ViolationKind.MALFORMED_MESSAGE,
        ViolationKind.NON_MONOTONIC_GLOBAL_POSITION,
    ]


def test_non_monotonic_violation_is_reported_before_the_malformed_one():
    # verify reports violations in the order its checks run. The
    # global_position check runs before the missing-field check.
    store = _ListStore(
        [
            _msg(2, "test::user-abc", 0),
            {"global_position": 2, "position": 1, "id": "b"},  # missing stream, dup gp
        ]
    )

    report = verify(store)

    assert [v.kind for v in report.violations] == [
        ViolationKind.NON_MONOTONIC_GLOBAL_POSITION,
        ViolationKind.MALFORMED_MESSAGE,
    ]


def test_duplicate_id_is_reported_before_the_position_gap_on_one_row():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0, id="dup"),
            _msg(2, "test::user-abc", 2, id="dup"),  # duplicate id and a gap
        ]
    )

    report = verify(store)

    assert [v.kind for v in report.violations] == [
        ViolationKind.DUPLICATE_MESSAGE_ID,
        ViolationKind.POSITION_GAP,
    ]


@pytest.mark.parametrize("missing_key", [False, True], ids=["null", "absent"])
def test_message_with_null_data_is_flagged_malformed(missing_key):
    # Message DB allows a NULL body. The row is reported, not skipped, and it
    # still holds its position: exactly one violation means the next row gets
    # no position_gap.
    null_row = _msg(2, "test::user-abc", 1, data=None)
    if missing_key:
        del null_row["data"]
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            null_row,
            _msg(3, "test::user-abc", 2),
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert report.message_count == 3
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == ViolationKind.MALFORMED_MESSAGE
    assert violation.stream == "test::user-abc"
    assert violation.position == 1
    assert violation.detail == "Message data is NULL."


@pytest.mark.parametrize(
    "data, type_name",
    [([], "list"), ("x", "str"), (0, "int"), (False, "bool")],
    ids=["array", "string", "number", "boolean"],
)
def test_message_with_non_object_data_is_flagged_malformed(data, type_name):
    # Message DB's ``data`` column is ``jsonb`` and can hold any JSON value. A
    # body that is not an object is reported, and the row keeps its position.
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user-abc", 1, data=data),
            _msg(3, "test::user-abc", 2),
        ]
    )

    report = verify(store)

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == ViolationKind.MALFORMED_MESSAGE
    assert violation.stream == "test::user-abc"
    assert violation.position == 1
    assert violation.detail == f"Message data is a {type_name}, not an object."


def test_message_with_empty_dict_data_is_clean():
    # An empty object is a valid body; only a NULL or non-object body is a
    # corruption.
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0, data={}),
            _msg(2, "test::user-abc", 1, data={}),
        ]
    )

    report = verify(store)

    assert report.ok is True
    assert report.violations == ()


def test_snapshot_with_null_data_is_reported_only_as_malformed_snapshot():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user:snapshot-abc", 0, data=None),
        ]
    )

    report = verify(store)

    assert [v.kind for v in report.violations] == [ViolationKind.MALFORMED_SNAPSHOT]


def test_row_missing_position_with_null_data_reports_only_the_missing_field():
    store = _ListStore(
        [
            {
                "global_position": 1,
                "stream_name": "test::user-abc",
                "id": "a",
                "data": None,
            },
        ]
    )

    report = verify(store)

    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == ViolationKind.MALFORMED_MESSAGE
    assert "position" in violation.detail
    assert "NULL" not in violation.detail


def test_report_violations_is_an_immutable_tuple():
    violation = IntegrityViolation(
        kind=ViolationKind.POSITION_GAP, stream=None, position=None, detail="d"
    )
    # A list passed at construction is stored as a tuple, so a caller cannot
    # append to a report after the fact.
    report = IntegrityReport(message_count=1, stream_count=0, violations=[violation])
    assert isinstance(report.violations, tuple)
    assert not hasattr(report.violations, "append")


@pytest.mark.parametrize(
    "kind, value",
    [
        (ViolationKind.DUPLICATE_MESSAGE_ID, "duplicate_message_id"),
        (ViolationKind.POSITION_GAP, "position_gap"),
        (ViolationKind.NON_MONOTONIC_GLOBAL_POSITION, "non_monotonic_global_position"),
        (ViolationKind.SNAPSHOT_AHEAD_OF_STREAM, "snapshot_ahead_of_stream"),
        (ViolationKind.MALFORMED_MESSAGE, "malformed_message"),
        (ViolationKind.MALFORMED_SNAPSHOT, "malformed_snapshot"),
    ],
)
def test_violation_kind_values_are_the_wire_tokens(kind, value):
    assert kind.value == value


def test_violation_kind_has_exactly_the_six_kinds():
    assert len(ViolationKind) == 6


def test_report_json_writes_the_kind_as_its_plain_string():
    report = verify(_ListStore([_msg(1, "test::user-abc", 3)]))

    payload = json.loads(json.dumps(report.as_dict()))

    assert payload["violations"][0]["kind"] == "position_gap"
