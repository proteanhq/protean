"""Port-level tests for ``BaseEventStore.verify()``.

``verify`` is concrete on the port and reads the whole store through the
``$all`` iterator, so its logic is identical for every adapter. These tests
drive it against a minimal in-file store whose ``$all`` pages over a preloaded
list of raw message dicts. That lets each invariant be violated
deterministically, including corruptions the real adapters do not readily
produce: MessageDB keys both ``id`` and ``global_position`` as unique, and the
memory adapter increments ``global_position`` and mints a fresh uuid4 ``id`` per
write. Those corruptions only arise from an out-of-band restore, which is
exactly what ``verify`` exists to catch.
"""

from typing import Any

import pytest

from protean.port.event_store import BaseEventStore


class _ListStore(BaseEventStore):
    """A concrete ``BaseEventStore`` backed by a preloaded list of raw dicts.

    Only ``$all`` reads are implemented (that is all ``verify`` uses), and they
    page by ``global_position`` exactly like the real adapters, so the iterator's
    paging is genuinely exercised.
    """

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        # Store-wide order is by global_position, matching the read contract.
        self._messages = sorted(messages, key=lambda m: m["global_position"])

    def _read(
        self,
        stream_name: str,
        sql: str | None = None,
        position: int = 0,
        no_of_messages: int = 1000,
    ) -> list[dict[str, Any]]:
        assert stream_name == "$all"
        page = [m for m in self._messages if m["global_position"] >= position]
        return page[:no_of_messages]

    # Unused abstract methods: verify never calls them.
    def _write(self, *args: Any, **kwargs: Any) -> int:  # pragma: no cover
        raise NotImplementedError

    def _read_last_message(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _stream_identifiers(
        self, *args: Any, **kwargs: Any
    ) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def _stream_head_position(
        self, *args: Any, **kwargs: Any
    ) -> int:  # pragma: no cover
        raise NotImplementedError

    def _data_reset(self) -> None:  # pragma: no cover
        raise NotImplementedError


def _msg(
    global_position: int,
    stream_name: str,
    position: int,
    *,
    id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "global_position": global_position,
        "stream_name": stream_name,
        "position": position,
        "id": id if id is not None else f"id-{global_position}",
        "type": "Event",
        "data": data or {},
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

    report = store.verify()

    assert report.ok is True
    assert report.violations == []
    assert report.message_count == 3
    assert report.stream_count == 2


def test_empty_store_is_clean():
    report = _ListStore([]).verify()

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

    report = store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == BaseEventStore.VERIFY_DUPLICATE_MESSAGE_ID
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

    report = store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == BaseEventStore.VERIFY_POSITION_GAP
    assert violation.stream == "test::user-abc"
    assert violation.position == 2
    assert "expected 1" in violation.detail


def test_position_gap_from_base_is_flagged():
    store = _ListStore([_msg(1, "test::user-abc", 3)])  # first message not at 0

    report = store.verify()

    assert report.ok is False
    assert report.violations[0].kind == BaseEventStore.VERIFY_POSITION_GAP
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

    report = store.verify()

    assert report.ok is False
    kinds = [v.kind for v in report.violations]
    assert BaseEventStore.VERIFY_NON_MONOTONIC_GLOBAL_POSITION in kinds


def test_snapshot_ahead_of_stream_head_is_flagged():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user-abc", 1),
            _msg(3, "test::user:snapshot-abc", 0, data={"_version": 5}),
        ]
    )

    report = store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == BaseEventStore.VERIFY_SNAPSHOT_AHEAD_OF_STREAM
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

    assert store.verify().ok is True


def test_snapshot_without_aggregate_stream_is_flagged():
    # A snapshot whose aggregate stream has no events at all: head is -1, so any
    # non-negative _version is ahead.
    store = _ListStore([_msg(1, "test::user:snapshot-orphan", 0, data={"_version": 0})])

    report = store.verify()

    assert report.ok is False
    assert report.violations[0].kind == BaseEventStore.VERIFY_SNAPSHOT_AHEAD_OF_STREAM


def test_snapshot_with_non_int_version_is_flagged_malformed():
    # A corrupt snapshot whose _version is not an integer is flagged as
    # malformed rather than silently skipped, and does not crash the scan.
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user:snapshot-abc", 0, data={"_version": "oops"}),
        ]
    )

    report = store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    assert report.violations[0].kind == BaseEventStore.VERIFY_MALFORMED_SNAPSHOT
    assert report.violations[0].stream == "test::user:snapshot-abc"


def test_snapshot_with_non_dict_data_is_flagged_malformed():
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user:snapshot-abc", 0, data=None),
        ]
    )

    report = store.verify()

    assert report.ok is False
    assert report.violations[0].kind == BaseEventStore.VERIFY_MALFORMED_SNAPSHOT


def test_snapshot_with_bool_version_is_flagged_malformed():
    # ``bool`` is an ``int`` subclass; a True/False _version must not slip
    # through the integer guard and be read as version 1/0.
    store = _ListStore(
        [
            _msg(1, "test::user-abc", 0),
            _msg(2, "test::user:snapshot-abc", 0, data={"_version": True}),
        ]
    )

    report = store.verify()

    assert report.ok is False
    assert report.violations[0].kind == BaseEventStore.VERIFY_MALFORMED_SNAPSHOT


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

    assert store.verify().ok is True


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

    report = store.verify()

    assert report.ok is False
    assert report.violations[0].kind == BaseEventStore.VERIFY_SNAPSHOT_AHEAD_OF_STREAM


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

    report = store.verify()

    assert report.ok is False
    kinds = sorted(v.kind for v in report.violations)
    assert kinds == [
        BaseEventStore.VERIFY_DUPLICATE_MESSAGE_ID,
        BaseEventStore.VERIFY_POSITION_GAP,
        BaseEventStore.VERIFY_SNAPSHOT_AHEAD_OF_STREAM,
    ]
    assert report.message_count == 5
    assert report.stream_count == 3


def test_iterator_pages_across_batches():
    # More messages than one page, all valid: exercises the paging loop and its
    # global_position + 1 advance without dropping or double-counting any.
    messages = [_msg(gp, "test::user-abc", gp - 1) for gp in range(1, 51)]
    store = _ListStore(messages)

    report = store.verify()

    assert report.ok is True
    assert report.message_count == 50

    # Force multiple pages with a tiny batch size and confirm every message is
    # yielded exactly once, in order.
    seen = [m["global_position"] for m in store._iter_all_messages(batch_size=7)]
    assert seen == list(range(1, 51))


def test_iterator_pages_across_sparse_global_positions():
    # global_position may have gaps (the memory adapter documents this). The
    # cursor advances past the highest gp seen, so a sparse sequence spanning
    # several pages must still yield every message exactly once.
    gps = [1, 8, 9, 40, 41, 300, 301, 999]
    store = _ListStore([_msg(gp, "test::user-abc", i) for i, gp in enumerate(gps)])

    seen = [m["global_position"] for m in store._iter_all_messages(batch_size=3)]

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

    report = store.verify()

    assert report.ok is False
    assert report.message_count == 2
    kinds = [v.kind for v in report.violations]
    assert kinds == [
        BaseEventStore.VERIFY_MALFORMED_MESSAGE,
        BaseEventStore.VERIFY_MALFORMED_MESSAGE,
    ]
    assert "position" in report.violations[0].detail
    assert "stream_name" in report.violations[1].detail
