"""Writes: the position a write returns and the row it stores.

A test that checks a stored row reads it back with `get_stream_messages`.
"""

from datetime import datetime

import pytest

from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.requires(EventStoreCapabilities.WRITE)

METADATA = {
    "domain": {"kind": "EVENT"},
    "headers": {"id": "msg-1", "type": "Registered", "stream": "user-1"},
}


def _write(adapter, stream_name: str, n: int) -> int:
    return adapter.write_message(stream_name, "Counted", {"n": n})


def test_the_first_write_to_a_stream_is_at_position_0(adapter):
    assert _write(adapter, "user-1", 0) == 0


def test_each_write_returns_the_next_stream_position(adapter):
    assert [_write(adapter, "user-1", n) for n in range(6)] == [0, 1, 2, 3, 4, 5]

    rows = adapter.get_stream_messages("user-1")

    assert [row["position"] for row in rows] == [0, 1, 2, 3, 4, 5]


def test_each_stream_numbers_its_positions_from_0(adapter):
    _write(adapter, "user-1", 0)
    _write(adapter, "user-1", 1)

    assert _write(adapter, "user-2", 2) == 0


def test_global_positions_increase_across_streams(adapter):
    _write(adapter, "user-1", 0)
    _write(adapter, "order-1", 1)
    _write(adapter, "user-1", 2)

    first, second = (
        adapter.get_stream_messages("user-1")[0],
        adapter.get_stream_messages("order-1")[0],
    )
    third = adapter.get_stream_messages("user-1")[1]

    assert first["global_position"] < second["global_position"]
    assert second["global_position"] < third["global_position"]


def test_a_written_row_carries_its_stream_type_data_and_metadata(adapter):
    adapter.write_message("user-1", "Registered", {"email": "a@example.com"}, METADATA)

    [row] = adapter.get_stream_messages("user-1")

    assert row["stream_name"] == "user-1"
    assert row["type"] == "Registered"
    assert row["position"] == 0
    assert row["data"] == {"email": "a@example.com"}
    # An adapter may add keys to the metadata it stores, so check the written ones.
    assert row["metadata"]["domain"]["kind"] == "EVENT"
    assert row["metadata"]["headers"]["id"] == "msg-1"
    assert isinstance(row["id"], str) and row["id"]
    assert isinstance(row["global_position"], int)
    assert isinstance(row["time"], datetime)


def test_a_write_without_metadata_stores_none(adapter):
    _write(adapter, "user-1", 0)

    [row] = adapter.get_stream_messages("user-1")

    assert row["metadata"] is None


def test_each_row_gets_its_own_id(adapter):
    for n in range(3):
        _write(adapter, "user-1", n)

    ids = [row["id"] for row in adapter.get_stream_messages("user-1")]

    assert len(set(ids)) == 3


def test_changing_the_written_data_leaves_the_stored_row_unchanged(adapter):
    data = {"n": 0, "tags": ["a"]}
    adapter.write_message("user-1", "Counted", data)

    data["tags"].append("b")

    assert adapter.get_stream_messages("user-1")[0]["data"] == {
        "n": 0,
        "tags": ["a"],
    }
