"""Integration tests for ``verify()`` against the real memory event store.

These lock the raw-dict contract ``verify`` depends on (the ``id``, ``position``,
``global_position``, ``stream_name``, and ``data`` keys) against the actual
adapter output. The exhaustive per-branch coverage lives in
``tests/port/test_event_store_verify.py``.
"""

from protean.adapters.event_store.memory import MemoryMessage


def _metadata(stream_name, message_type, message_id):
    return {
        "domain": {"kind": "EVENT"},
        "headers": {"id": message_id, "type": message_type, "stream": stream_name},
    }


def _seed_two_events(store):
    store._write(
        "test::user-abc",
        "Registered",
        {"n": 1},
        _metadata("test::user-abc", "Registered", "m1"),
    )
    store._write(
        "test::user-abc",
        "Renamed",
        {"n": 2},
        _metadata("test::user-abc", "Renamed", "m2"),
    )


def test_clean_store_passes(test_domain):
    store = test_domain.event_store.store
    _seed_two_events(store)
    store._write("test::user:snapshot-abc", "SNAPSHOT", {"_version": 1})

    report = store.verify()

    assert report.ok is True
    assert report.violations == ()
    assert report.message_count == 3
    assert report.stream_count == 2


def test_empty_store_passes(test_domain):
    report = test_domain.event_store.store.verify()

    assert report.ok is True
    assert report.message_count == 0


def test_duplicate_message_id_is_caught(test_domain):
    store = test_domain.event_store.store
    _seed_two_events(store)

    repo = store.domain.repository_for(MemoryMessage)
    rows = repo._dao.query.order_by("global_position").all().items
    # Point the second row's store id at the first, forging a duplicate.
    rows[1].id = rows[0].id
    repo.add(rows[1])

    report = store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    assert report.violations[0].kind == store.VERIFY_DUPLICATE_MESSAGE_ID
    assert report.violations[0].stream == "test::user-abc"


def test_position_gap_is_caught_and_named(test_domain):
    store = test_domain.event_store.store
    _seed_two_events(store)

    repo = store.domain.repository_for(MemoryMessage)
    # Append a row that skips position 2.
    repo.add(
        MemoryMessage(
            stream_name="test::user-abc",
            position=3,
            type="Skipped",
            data={},
            global_position=999,
        )
    )

    report = store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == store.VERIFY_POSITION_GAP
    assert violation.stream == "test::user-abc"
    assert violation.position == 3


def test_snapshot_ahead_of_stream_head_is_caught(test_domain):
    store = test_domain.event_store.store
    _seed_two_events(store)  # head position is 1
    store._write("test::user:snapshot-abc", "SNAPSHOT", {"_version": 5})

    report = store.verify()

    assert report.ok is False
    assert len(report.violations) == 1
    violation = report.violations[0]
    assert violation.kind == store.VERIFY_SNAPSHOT_AHEAD_OF_STREAM
    assert violation.stream == "test::user:snapshot-abc"
