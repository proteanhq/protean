"""Stream reads page by the stream ``position``, inclusive of it."""

import pytest

from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.requires(EventStoreCapabilities.READ_STREAM)


def _write(adapter, stream_name: str, n: int) -> None:
    adapter.write_message(stream_name, "Counted", {"n": n})


def _numbers(rows) -> list[int]:
    return [row["data"]["n"] for row in rows]


def test_an_empty_stream_returns_no_rows(adapter):
    assert adapter.get_stream_messages("user-1") == []


def test_returns_the_stream_in_position_order(adapter):
    for n in range(5):
        _write(adapter, "user-1", n)

    rows = adapter.get_stream_messages("user-1")

    assert [row["position"] for row in rows] == [0, 1, 2, 3, 4]
    assert _numbers(rows) == [0, 1, 2, 3, 4]


def test_reads_from_the_given_position_inclusive(adapter):
    for n in range(5):
        _write(adapter, "user-1", n)

    rows = adapter.get_stream_messages("user-1", position=2)

    assert [row["position"] for row in rows] == [2, 3, 4]


def test_returns_at_most_limit_rows(adapter):
    for n in range(5):
        _write(adapter, "user-1", n)

    rows = adapter.get_stream_messages("user-1", position=1, limit=2)

    assert [row["position"] for row in rows] == [1, 2]


def test_returns_only_the_named_stream(adapter):
    for n in range(3):
        _write(adapter, "user-1", n)
        _write(adapter, "user-2", 10 + n)

    rows = adapter.get_stream_messages("user-2")

    assert [row["stream_name"] for row in rows] == ["user-2"] * 3
    assert _numbers(rows) == [10, 11, 12]


def test_pages_by_stream_position_not_global_position(adapter):
    # Rows of another stream come first, so the global positions of
    # ``user-2`` are higher than its stream positions.
    for n in range(3):
        _write(adapter, "user-1", n)
    for n in range(3):
        _write(adapter, "user-2", 10 + n)

    rows = adapter.get_stream_messages("user-2", position=1)

    assert _numbers(rows) == [11, 12]


def test_a_position_past_the_end_returns_no_rows(adapter):
    _write(adapter, "user-1", 0)

    assert adapter.get_stream_messages("user-1", position=5) == []


def test_changing_a_read_result_leaves_the_stored_row_unchanged(adapter):
    adapter.write_message("user-1", "Counted", {"n": 0, "tags": ["a"]})

    row = adapter.get_stream_messages("user-1")[0]
    row["data"]["tags"].append("b")
    row["position"] = 99

    assert [
        (row["position"], row["data"]) for row in adapter.get_stream_messages("user-1")
    ] == [(0, {"n": 0, "tags": ["a"]})]
