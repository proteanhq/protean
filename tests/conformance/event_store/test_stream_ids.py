"""The ids of the streams in a category.

The Port does not promise an order, and the stores return the ids in different
orders, so each test compares the ids as a set.
"""

import pytest

from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.requires(EventStoreCapabilities.READ_CATEGORY)


def _write(adapter, stream_name: str, n: int) -> None:
    adapter.write_message(stream_name, "Counted", {"n": n})


@pytest.mark.parametrize("prefix", ["", "test::"], ids=["plain", "prefixed"])
def test_lists_only_the_ids_of_the_exact_category(adapter, prefix):
    _write(adapter, f"{prefix}user-1", 0)
    _write(adapter, f"{prefix}poweruser-2", 1)
    adapter.write_message(f"{prefix}user:snapshot-3", "SNAPSHOT", {"_version": 0})

    assert set(adapter.stream_ids(f"{prefix}user")) == {"1"}


def test_lists_each_id_once(adapter):
    _write(adapter, "user-1", 0)
    _write(adapter, "user-2", 1)
    _write(adapter, "user-1", 2)
    _write(adapter, "order-3", 3)

    ids = adapter.stream_ids("user")

    assert set(ids) == {"1", "2"}
    assert len(ids) == 2


def test_an_empty_category_has_no_ids(adapter):
    _write(adapter, "order-1", 0)

    assert list(adapter.stream_ids("user")) == []
