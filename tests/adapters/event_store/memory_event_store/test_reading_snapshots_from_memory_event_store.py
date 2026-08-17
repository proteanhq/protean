"""Reading a store that also holds snapshot rows.

Snapshot rows are written with ``type == "SNAPSHOT"`` and no metadata (see
``_load_aggregate_current`` / ``create_snapshot``). ``read`` and ``read_all``
must skip them: deserializing a snapshot's ``None`` metadata raises, and both
readers are contracted to yield events and commands only. ``read_all`` pages on
raw rows, so a snapshot interleaved in ``$all`` must neither truncate the read
nor desync the paging cursor.

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
