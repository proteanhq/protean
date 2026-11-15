"""The ids of the streams in a category.

The Port promises the ids sorted and each id once.
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

    assert adapter.stream_ids(f"{prefix}user") == ["1"]


def test_lists_each_id_once(adapter):
    _write(adapter, "user-1", 0)
    _write(adapter, "user-2", 1)
    _write(adapter, "user-1", 2)
    _write(adapter, "order-3", 3)

    assert adapter.stream_ids("user") == ["1", "2"]


def test_lists_the_ids_sorted(adapter):
    # Written out of order, so a store that returns write order fails.
    _write(adapter, "user-c", 0)
    _write(adapter, "user-a", 1)
    _write(adapter, "user-b", 2)

    assert adapter.stream_ids("user") == ["a", "b", "c"]


def test_an_empty_category_has_no_ids(adapter):
    _write(adapter, "order-1", 0)

    assert adapter.stream_ids("user") == []
