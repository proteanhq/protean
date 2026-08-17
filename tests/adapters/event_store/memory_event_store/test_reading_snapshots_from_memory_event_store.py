"""Reading a store that also holds snapshot rows.

Snapshot rows are written with ``type == "SNAPSHOT"`` and no metadata (see
``_load_aggregate_current`` / ``create_snapshot``). ``read`` and ``read_all``
must skip them: deserializing a snapshot's ``None`` metadata raises, and both
readers are contracted to yield events and commands only. ``read_all`` pages on
raw rows, so a snapshot interleaved in ``$all`` must neither truncate the read
nor desync the paging cursor.
"""

from unittest.mock import patch

import protean.port.event_store as event_store_module
from protean.utils.eventing import Message


def _metadata(stream_name, message_type, message_id):
    return {
        "domain": {"kind": "EVENT"},
        "headers": {"id": message_id, "type": message_type, "stream": stream_name},
    }


def _write_event(store, stream_name, n):
    """Write one event carrying ``{"n": n}`` to ``stream_name``."""
    store._write(
        stream_name,
        "Ticked",
        {"n": n},
        _metadata(stream_name, "Ticked", f"{stream_name}-{n}"),
    )


def _write_snapshot(store, category, identifier, version=0):
    """Write a snapshot row the way the store does: type SNAPSHOT, no metadata."""
    store._write(f"{category}:snapshot-{identifier}", "SNAPSHOT", {"_version": version})


def _types(messages):
    return [m.metadata.headers.type for m in messages]


def _ns(messages):
    return [m.data["n"] for m in messages]


def test_read_all_over_store_with_snapshot_yields_events_only(test_domain):
    """``read_all("$all")`` returns every event, raises nothing, and skips the
    snapshot rows that would otherwise raise on deserialize."""
    store = test_domain.event_store.store
    for i in range(4):
        _write_event(store, "user-1", i)
    _write_snapshot(store, "user", "1")

    messages = list(store.read_all("$all"))

    assert len(messages) == 4, "Expected the four events, got a different count"
    assert all(isinstance(m, Message) for m in messages)
    assert "SNAPSHOT" not in _types(messages)
    assert _ns(messages) == [0, 1, 2, 3]


def test_read_all_stream_reads_over_store_with_snapshot_does_not_raise(test_domain):
    """``read("$all")`` on a store containing a snapshot returns the events and
    raises nothing — the original bug was a ``TypeError`` from the snapshot's
    ``None`` metadata."""
    store = test_domain.event_store.store
    for i in range(3):
        _write_event(store, "user-1", i)
    _write_snapshot(store, "user", "1")

    messages = store.read("$all")

    assert len(messages) == 3
    assert "SNAPSHOT" not in _types(messages)
    assert _ns(messages) == [0, 1, 2]


def test_read_all_snapshot_on_page_boundary_drops_no_events(test_domain):
    """A snapshot sitting as the last raw row of a full page must not end the
    read early nor duplicate a row.

    With ``page_size=2`` the snapshot is the second (last) raw row of the first
    page. If ``read_all`` paged on filtered messages instead of raw rows, the
    first page would deserialize to a single event, read as short, and terminate
    — dropping every later event. Paging on raw rows keeps all four events.
    """
    store = test_domain.event_store.store
    _write_event(store, "user-1", 0)
    _write_snapshot(store, "user", "1")  # global-position 2, last row of page 1
    _write_event(store, "user-1", 1)
    _write_event(store, "user-1", 2)
    _write_event(store, "user-1", 3)

    messages = list(store.read_all("$all", page_size=2))

    assert _ns(messages) == [0, 1, 2, 3], "an event was dropped or duplicated"
    assert "SNAPSHOT" not in _types(messages)


def test_read_all_full_page_of_only_snapshots_still_advances(test_domain):
    """A full page made up entirely of snapshot rows must still advance the
    cursor and continue, not stop and drop the events after it.

    With ``page_size=2`` the first page is two snapshots (zero events yielded).
    A reader that terminated on the yielded count would stop here and lose the
    event; paging on raw rows advances past both snapshots and reads it.
    """
    store = test_domain.event_store.store
    _write_snapshot(store, "user", "1")
    _write_snapshot(store, "user", "2")
    _write_event(store, "user-1", 0)

    messages = list(store.read_all("$all", page_size=2))

    assert _ns(messages) == [0]
    assert "SNAPSHOT" not in _types(messages)


def test_read_all_page_size_one_with_snapshot(test_domain):
    """``page_size=1`` walks one raw row at a time; a snapshot row yields nothing
    for its page but must not stop or re-loop the read."""
    store = test_domain.event_store.store
    _write_event(store, "user-1", 0)
    _write_snapshot(store, "user", "1")
    _write_event(store, "user-1", 1)

    messages = list(store.read_all("$all", page_size=1))

    assert _ns(messages) == [0, 1]
    assert "SNAPSHOT" not in _types(messages)


def test_read_last_message_skips_a_trailing_snapshot(test_domain):
    """``read_last_message("$all")`` must return the newest event, not raise,
    when a snapshot is the newest raw row.

    Outbox reconciliation reads ``$all`` this way. A snapshot written after the
    last event would otherwise be the tail row, and deserializing its ``None``
    metadata would crash the reconcile sweep.
    """
    store = test_domain.event_store.store
    for i in range(3):
        _write_event(store, "user-1", i)
    _write_snapshot(store, "user", "1")  # newest raw row in `$all`

    last = store.read_last_message("$all")

    assert last is not None
    assert last.metadata.headers.type != "SNAPSHOT"
    assert last.data["n"] == 2


def test_read_last_message_walks_back_over_a_run_of_snapshots(test_domain):
    """When the tail is a run of snapshots longer than one scan window, the
    backward walk crosses all of them and returns the newest event beneath.

    A single loading batch can snapshot several aggregates in a row, leaving
    more consecutive snapshot rows at the tail of ``$all`` than one window
    holds. The window is shrunk here so two events and three trailing snapshots
    already span more than one window.
    """
    store = test_domain.event_store.store
    _write_event(store, "user-1", 0)
    _write_event(store, "user-1", 1)
    _write_snapshot(store, "user", "1")
    _write_snapshot(store, "user", "2")
    _write_snapshot(store, "user", "3")  # three trailing snapshots > one window

    with patch.object(event_store_module, "_SNAPSHOT_TAIL_WINDOW", 2):
        last = store.read_last_message("$all")

    assert last is not None
    assert last.metadata.headers.type != "SNAPSHOT"
    assert last.data["n"] == 1


def test_read_last_message_scan_is_bounded_near_the_tail(test_domain):
    """The snapshot-skip scan reads a bounded window near the tail, never a
    capped scan from the start.

    The old helper read from position 0 with ``no_of_messages=1_000_000`` and
    took the max, which on a store past that cap returns a stale non-tail row.
    Here the window is shrunk to 2, so the scan must start at the tail's
    position and read at most two rows, not from position 0.
    """
    store = test_domain.event_store.store
    for i in range(6):
        _write_event(store, "user-1", i)  # global positions 1..6
    _write_snapshot(store, "user", "1")  # tail, global position 7

    with patch.object(event_store_module, "_SNAPSHOT_TAIL_WINDOW", 2):
        with patch.object(store, "_read", wraps=store._read) as spy:
            last = store.read_last_message("$all")

    assert last is not None
    assert last.data["n"] == 5  # the newest event, not a stale one

    # Every scan read stayed a bounded window at the tail: none from position 0,
    # and none the old 1_000_000-row full scan.
    assert spy.call_args_list, "the snapshot tail should have triggered a scan"
    for call in spy.call_args_list:
        assert call.kwargs["position"] > 0
        assert call.kwargs["no_of_messages"] == 2


def test_read_last_message_none_when_only_snapshots(test_domain):
    """A store holding only snapshot rows has no event to return, so
    ``read_last_message`` yields ``None`` rather than raising."""
    store = test_domain.event_store.store
    _write_snapshot(store, "user", "1")
    _write_snapshot(store, "user", "2")

    assert store.read_last_message("$all") is None


def test_category_read_over_store_with_snapshot_unchanged(test_domain):
    """A category read returns the category's events and never a snapshot row,
    matching the pre-snapshot behaviour (acceptance criterion 3)."""
    store = test_domain.event_store.store
    for i in range(3):
        _write_event(store, "user-1", i)
    _write_snapshot(store, "user", "1")

    paged = list(store.read_all("user", page_size=2))
    direct = store.read("user")

    assert _ns(paged) == [0, 1, 2]
    assert _ns(direct) == [0, 1, 2]
    assert "SNAPSHOT" not in _types(paged)
    assert "SNAPSHOT" not in _types(direct)
