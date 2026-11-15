"""Integration tests for ``verify()`` against the real memory event store.

These lock the raw-dict contract ``verify`` depends on (the ``id``, ``position``,
``global_position``, ``stream_name``, and ``data`` keys) against the actual
adapter output. The exhaustive per-branch coverage lives in
``tests/event_store/test_verify.py``.
"""

from datetime import UTC, datetime

from protean.infra.integrity import ViolationKind


def _metadata(stream_name, message_type, message_id):
    return {
        "domain": {"kind": "EVENT"},
        "headers": {"id": message_id, "type": message_type, "stream": stream_name},
    }


def _seed_two_events(store):
    store.write_message(
        "test::user-abc",
        "Registered",
        {"n": 1},
        _metadata("test::user-abc", "Registered", "m1"),
    )
    store.write_message(
        "test::user-abc",
        "Renamed",
        {"n": 2},
        _metadata("test::user-abc", "Renamed", "m2"),
    )


def test_clean_store_passes(test_domain):
    store = test_domain.event_store.store
    _seed_two_events(store)
    store.write_message("test::user:snapshot-abc", "SNAPSHOT", {"_version": 1})

    report = test_domain.event_store.verify()

    assert report.ok is True
    assert report.violations == ()
    assert report.message_count == 3
    assert report.stream_count == 2


def test_empty_store_passes(test_domain):
    report = test_domain.event_store.verify()

    assert report.ok is True
    assert report.message_count == 0


def test_duplicate_message_id_is_caught(test_domain):
    store = test_domain.event_store.store
    _seed_two_events(store)

    rows = store.get_connection()
    # Point the second row's store id at the first, forging a duplicate.
    rows[1]["id"] = rows[0]["id"]

    report = test_domain.event_store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    assert report.violations[0].kind == ViolationKind.DUPLICATE_MESSAGE_ID
    assert report.violations[0].stream == "test::user-abc"


def test_position_gap_is_caught_and_named(test_domain):
    store = test_domain.event_store.store
    _seed_two_events(store)

    # Append a row that skips position 2.
    store.get_connection().append(
        {
            "id": "skipped",
            "stream_name": "test::user-abc",
            "type": "Skipped",
            "position": 3,
            "global_position": 999,
            "data": {},
            "metadata": None,
            "time": datetime.now(UTC),
        }
    )

    report = test_domain.event_store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == ViolationKind.POSITION_GAP
    assert violation.stream == "test::user-abc"
    assert violation.position == 3


def test_snapshot_ahead_of_stream_head_is_caught(test_domain):
    store = test_domain.event_store.store
    _seed_two_events(store)  # head position is 1
    store.write_message("test::user:snapshot-abc", "SNAPSHOT", {"_version": 5})

    report = test_domain.event_store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == ViolationKind.SNAPSHOT_AHEAD_OF_STREAM
    assert violation.stream == "test::user:snapshot-abc"


def test_message_with_null_data_is_caught(test_domain):
    store = test_domain.event_store.store
    _seed_two_events(store)
    store.write_message(
        "test::user-abc",
        "Closed",
        {"n": 3},
        _metadata("test::user-abc", "Closed", "m3"),
    )

    rows = store.get_connection()
    # Null the body of the middle row (position 1).
    rows[1]["data"] = None

    report = test_domain.event_store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == ViolationKind.MALFORMED_MESSAGE
    assert violation.stream == "test::user-abc"
    assert violation.position == 1
