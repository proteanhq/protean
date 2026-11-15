"""An adapter that manages its own schema creates and drops its tables.

Neither built-in event store declares ``SCHEMA_MANAGEMENT``, so these tests run
only against an adapter that does.
"""

import pytest

from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.requires(
    EventStoreCapabilities.SCHEMA_MANAGEMENT,
    EventStoreCapabilities.WRITE,
    EventStoreCapabilities.READ_STREAM,
)


def test_a_created_schema_takes_writes_and_reads(adapter):
    adapter.create_schema()

    adapter.write_message("user-1", "Counted", {"n": 0})

    assert [row["data"] for row in adapter.get_stream_messages("user-1")] == [{"n": 0}]


def test_creating_the_schema_twice_keeps_its_rows(adapter):
    adapter.create_schema()
    adapter.write_message("user-1", "Counted", {"n": 0})

    adapter.create_schema()

    assert [row["data"] for row in adapter.get_stream_messages("user-1")] == [{"n": 0}]


def test_dropping_and_creating_the_schema_leaves_an_empty_store(adapter):
    adapter.create_schema()
    adapter.write_message("user-1", "Counted", {"n": 0})

    adapter.drop_schema()
    adapter.create_schema()

    assert adapter.get_stream_messages("user-1") == []
    assert adapter.write_message("user-1", "Counted", {"n": 1}) == 0
