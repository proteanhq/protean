"""Reads of the whole store page by ``global_position``, inclusive of it."""

import pytest

from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.requires(EventStoreCapabilities.READ_ALL)


def _write(adapter, stream_name: str, n: int) -> None:
    adapter.write_message(stream_name, "Counted", {"n": n})


def _numbers(rows) -> list[int]:
    return [row["data"]["n"] for row in rows]


def _write_three_categories(adapter) -> None:
    for n, stream_name in enumerate(
        ["user-1", "user-1", "order-1", "user-2", "payment-1"]
    ):
        _write(adapter, stream_name, n)


def test_an_empty_store_returns_no_rows(adapter):
    assert adapter.get_all_messages() == []


def test_returns_every_stream_in_global_position_order(adapter):
    _write_three_categories(adapter)

    rows = adapter.get_all_messages()

    positions = [row["global_position"] for row in rows]
    assert positions == sorted(positions)
    assert len(set(positions)) == 5
    assert [row["stream_name"] for row in rows] == [
        "user-1",
        "user-1",
        "order-1",
        "user-2",
        "payment-1",
    ]


def test_reads_from_the_given_global_position_inclusive(adapter):
    _write_three_categories(adapter)
    rows = adapter.get_all_messages()
    assert len(rows) == 5

    page = adapter.get_all_messages(position=rows[1]["global_position"])

    assert [row["id"] for row in page] == [row["id"] for row in rows[1:]]


def test_returns_at_most_limit_rows(adapter):
    _write_three_categories(adapter)
    rows = adapter.get_all_messages()

    page = adapter.get_all_messages(position=rows[1]["global_position"], limit=2)

    assert _numbers(page) == [1, 2]


def test_a_position_past_the_last_row_returns_no_rows(adapter):
    _write_three_categories(adapter)
    last = adapter.get_all_messages()[-1]

    assert adapter.get_all_messages(position=last["global_position"] + 1) == []
