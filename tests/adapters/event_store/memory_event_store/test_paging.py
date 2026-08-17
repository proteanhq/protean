"""Paging the whole store with ``read_all`` on the memory event store.

``read_all`` loops ``read`` in bounded pages and advances a cursor until a short
page, so a cold-load reader (projection rebuild, backup, verify) reads the whole
stream without the ``no_of_messages=1_000_000`` sentinel that silently truncates
past the read cap.
"""

from unittest.mock import patch

import pytest

from protean.exceptions import IncorrectUsageError
from protean.port.event_store import BaseEventStore


def _metadata(stream_name, message_type, message_id):
    return {
        "domain": {"kind": "EVENT"},
        "headers": {"id": message_id, "type": message_type, "stream": stream_name},
    }


def _write_n(store, stream_name, count):
    """Write ``count`` messages to ``stream_name``."""
    for i in range(count):
        store._write(
            stream_name,
            "Ticked",
            {"n": i},
            _metadata(stream_name, "Ticked", f"{stream_name}-{i}"),
        )


def _global_positions(messages):
    return [m.metadata.event_store.global_position for m in messages]


def test_read_all_pages_across_boundary_no_gaps_no_dups(test_domain):
    """A store holding ``page_size + 5`` messages is fully paged, in order."""
    store = test_domain.event_store.store
    page_size = 10
    _write_n(store, "counter-1", page_size + 5)

    paged = list(store.read_all("$all", page_size=page_size))
    gpos = _global_positions(paged)

    assert len(gpos) == page_size + 5  # nothing truncated at the read cap
    assert gpos == sorted(gpos)  # global_position order
    assert len(set(gpos)) == len(gpos)  # no duplicates across the boundary
    # The same messages a single uncapped read would return.
    baseline = _global_positions(store.read("$all", no_of_messages=1_000_000))
    assert gpos == baseline


def test_read_all_exact_multiple_of_page_size(test_domain):
    """A store whose size is an exact multiple of ``page_size`` returns every
    message once, then terminates with a single extra empty read.

    The final full page is followed by an empty page: the branch a partial-page
    test never exercises, and where an off-by-one in the terminate condition
    would drop the boundary row or loop.
    """
    store = test_domain.event_store.store
    page_size = 5
    _write_n(store, "counter-1", page_size * 2)

    with patch.object(store, "_read", wraps=store._read) as spy:
        paged = list(store.read_all("$all", page_size=page_size))

    gpos = _global_positions(paged)
    assert len(gpos) == page_size * 2
    assert len(set(gpos)) == page_size * 2  # no boundary-row duplicate
    assert gpos == sorted(gpos)
    # Two full pages, then one empty read that signals the end.
    assert spy.call_count == 3


def test_read_all_page_size_one(test_domain):
    """``page_size=1`` reads one row at a time without looping or dropping.

    This is the size where a dropped ``+ 1`` in the cursor advance would hang
    (re-reading the same single row forever) instead of merely duplicating.
    """
    store = test_domain.event_store.store
    _write_n(store, "counter-1", 5)

    paged = list(store.read_all("$all", page_size=1))
    gpos = _global_positions(paged)

    assert len(gpos) == 5
    assert gpos == sorted(gpos)
    assert len(set(gpos)) == 5


def test_read_all_empty_stream_yields_nothing_in_one_read(test_domain):
    """An empty stream yields nothing and issues a single underlying read."""
    store = test_domain.event_store.store

    with patch.object(store, "_read", wraps=store._read) as spy:
        result = list(store.read_all("$all", page_size=10))

    assert result == []
    assert spy.call_count == 1


def test_read_all_specific_stream_pages_by_position(test_domain):
    """A specific stream (``category-id``) pages by its per-stream ``position``."""
    store = test_domain.event_store.store
    _write_n(store, "counter-1", 7)
    # A second stream in the same category must not leak into a specific read.
    _write_n(store, "counter-2", 4)

    paged = list(store.read_all("counter-1", page_size=3))

    assert len(paged) == 7
    assert all(m.metadata.headers.stream == "counter-1" for m in paged)
    positions = [m.metadata.event_store.position for m in paged]
    assert positions == list(range(7))  # gapless per-stream, in order


def test_read_all_specific_stream_with_interleaved_writes(test_domain):
    """A specific stream pages by per-stream ``position`` even when a sibling
    stream's rows sit between its rows in ``global_position`` order.

    Writes alternate between the two streams, so ``counter-1``'s global
    positions are non-contiguous. Paging this stream by ``global_position``
    would skip rows; paging by per-stream ``position`` returns all of them.
    """
    store = test_domain.event_store.store
    for i in range(6):
        _write_n(store, "counter-1", 1)
        if i < 4:
            _write_n(store, "counter-2", 1)

    paged = list(store.read_all("counter-1", page_size=2))

    assert all(m.metadata.headers.stream == "counter-1" for m in paged)
    positions = [m.metadata.event_store.position for m in paged]
    assert positions == list(range(6))  # every row, none skipped by interleaving


def test_read_all_category_pages_by_global_position(test_domain):
    """A bare category read pages by ``global_position`` across its streams."""
    store = test_domain.event_store.store
    _write_n(store, "counter-1", 6)
    _write_n(store, "counter-2", 6)

    paged = list(store.read_all("counter", page_size=5))
    gpos = _global_positions(paged)

    assert len(gpos) == 12
    assert gpos == sorted(gpos)
    assert len(set(gpos)) == 12


def test_read_all_category_excludes_other_categories(test_domain):
    """A category read returns only that category's streams, not the whole store."""
    store = test_domain.event_store.store
    _write_n(store, "counter-1", 4)
    _write_n(store, "other-1", 3)

    paged = list(store.read_all("counter", page_size=2))

    assert len(paged) == 4
    assert all(m.metadata.headers.stream.startswith("counter-") for m in paged)


def test_read_all_defaults_to_all_stream(test_domain):
    """``read_all()`` with no stream reads ``$all``."""
    store = test_domain.event_store.store
    _write_n(store, "counter-1", 3)

    assert len(list(store.read_all())) == 3


@pytest.mark.parametrize("bad", [0, -1, 1.5, None])
def test_read_all_rejects_non_positive_page_size(test_domain, bad):
    """A page size that is not a positive integer is a usage error, not an
    infinite loop or a bare TypeError from the adapter's row limit."""
    store = test_domain.event_store.store

    with pytest.raises(IncorrectUsageError, match="page_size"):
        list(store.read_all("$all", page_size=bad))


def test_next_cursor_raises_when_position_absent():
    """A raw row with no position field raises instead of looping.

    The paging cursor cannot advance without a position, so a corrupt/missing
    one is a loud error rather than a silent infinite loop or truncated read.
    """
    raw_message = {"type": "X", "data": {}, "metadata": {"headers": {"id": "1"}}}

    with pytest.raises(IncorrectUsageError, match="missing its position"):
        BaseEventStore._next_cursor(raw_message, by_global_position=True)


def test_next_cursor_raises_when_chosen_position_is_none():
    """A raw row can carry one position field and not the other — asking for the
    absent one still raises rather than advancing on ``None``."""
    # `position` is set but `global_position` is absent. Asking for the global
    # cursor must still raise.
    raw_message = {
        "type": "X",
        "data": {},
        "position": 3,
        "metadata": {"headers": {"id": "1"}},
    }

    with pytest.raises(IncorrectUsageError, match="missing its position"):
        BaseEventStore._next_cursor(raw_message, by_global_position=True)
