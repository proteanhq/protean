"""``verify()`` on the SQL event store, which keeps snapshots out of ``$all``."""

from protean.infra.integrity import ViolationKind, verify


def seed(store):
    store.write_message("user-1", "Registered", {"n": 1})
    store.write_message("user-1", "Renamed", {"n": 2})


def test_a_valid_snapshot_passes(store):
    seed(store)
    store.write_message("user:snapshot-1", "SNAPSHOT", {"_version": 1})

    report = verify(store)

    assert report.ok is True
    assert report.message_count == 2
    assert report.stream_count == 1


def test_a_malformed_snapshot_is_caught(store):
    seed(store)
    store.write_message("user:snapshot-1", "SNAPSHOT", {"state": "no version"})

    report = verify(store)

    assert [(v.kind, v.stream) for v in report.violations] == [
        (ViolationKind.MALFORMED_SNAPSHOT, "user:snapshot-1")
    ]


def test_a_snapshot_ahead_of_its_stream_is_caught(store):
    seed(store)
    store.write_message("user:snapshot-1", "SNAPSHOT", {"_version": 5})

    report = verify(store)

    assert [(v.kind, v.stream) for v in report.violations] == [
        (ViolationKind.SNAPSHOT_AHEAD_OF_STREAM, "user:snapshot-1")
    ]
    assert "head position 1" in report.violations[0].detail
