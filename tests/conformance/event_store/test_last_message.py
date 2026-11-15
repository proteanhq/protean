"""The newest row of a stream, of a category and of the whole store."""

import pytest

from protean.port.event_store import EventStoreCapabilities


def _write(adapter, stream_name: str, n: int) -> None:
    adapter.write_message(stream_name, "Counted", {"n": n})


@pytest.mark.requires(EventStoreCapabilities.READ_STREAM)
class TestLastStreamMessage:
    def test_returns_the_newest_row_of_the_stream(self, adapter):
        for n in range(5):
            _write(adapter, "user-1", n)
        _write(adapter, "user-2", 5)

        last = adapter.get_last_stream_message("user-1")

        assert last["stream_name"] == "user-1"
        assert last["position"] == 4
        assert last["data"] == {"n": 4}

    def test_an_empty_stream_returns_none(self, adapter):
        _write(adapter, "user-1", 0)

        assert adapter.get_last_stream_message("user-2") is None

    def test_returns_the_newest_row_of_a_stream_longer_than_one_read_page(
        self, adapter
    ):
        # One row more than the default ``limit`` of a stream read, so an
        # adapter that reads one page and takes its last row returns a stale one.
        total = 1_001
        for n in range(total):
            _write(adapter, "checkpoint-1", n)

        last = adapter.get_last_stream_message("checkpoint-1")

        assert last["position"] == total - 1
        assert last["data"] == {"n": total - 1}


@pytest.mark.requires(EventStoreCapabilities.READ_CATEGORY)
class TestLastCategoryMessage:
    def test_returns_the_newest_row_across_the_streams_of_the_category(self, adapter):
        # The newest row goes to the shorter stream, so an adapter that picks
        # the row with the highest per-stream position returns the wrong one.
        _write(adapter, "user-1", 0)
        _write(adapter, "user-1", 1)
        _write(adapter, "user-2", 2)
        _write(adapter, "order-1", 3)

        last = adapter.get_last_category_message("user")

        assert last["stream_name"] == "user-2"
        assert last["position"] == 0
        assert last["data"] == {"n": 2}
        assert last["global_position"] == max(
            row["global_position"] for row in adapter.get_category_messages("user")
        )

    def test_leaves_out_a_longer_category_and_the_snapshot_streams(self, adapter):
        _write(adapter, "user-1", 0)
        _write(adapter, "user-1", 1)
        _write(adapter, "poweruser-2", 2)
        adapter.write_message("user:snapshot-3", "SNAPSHOT", {"_version": 0})

        last = adapter.get_last_category_message("user")

        assert last["stream_name"] == "user-1"
        assert last["data"] == {"n": 1}

    def test_includes_the_stream_named_as_the_category(self, adapter):
        _write(adapter, "user-1", 0)
        _write(adapter, "user", 1)

        assert adapter.get_last_category_message("user")["stream_name"] == "user"

    def test_each_category_has_its_own_newest_row(self, adapter):
        for n in range(3):
            _write(adapter, f"user-{n}", n)
        for n in range(3, 5):
            _write(adapter, f"order-{n}", n)

        assert adapter.get_last_category_message("user")["data"] == {"n": 2}
        assert adapter.get_last_category_message("order")["data"] == {"n": 4}

    def test_an_empty_category_returns_none(self, adapter):
        _write(adapter, "order-1", 0)

        assert adapter.get_last_category_message("user") is None


@pytest.mark.requires(EventStoreCapabilities.READ_ALL)
class TestLastMessage:
    def test_returns_the_last_row_written_to_any_stream(self, adapter):
        _write(adapter, "user-1", 0)
        _write(adapter, "order-2", 1)
        _write(adapter, "user-1", 2)
        _write(adapter, "payment-3", 3)

        last = adapter.get_last_message()

        assert last["stream_name"] == "payment-3"
        assert last["data"] == {"n": 3}
        assert last["global_position"] == max(
            row["global_position"] for row in adapter.get_all_messages()
        )

    def test_an_empty_store_returns_none(self, adapter):
        assert adapter.get_last_message() is None
