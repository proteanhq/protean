"""Check the programmatic API on docs/reference/cli/data/snapshot.md.

The example builds an ``Identity`` domain with two event-sourced aggregates.
It registers two users, ``abc-123`` and ``def-456``, and places one order.
Then it runs the three snapshot calls the page shows. Each test loads the
example fresh, so every test gets its own domain and memory event store.
"""

import pytest

from protean.exceptions import ObjectNotFoundError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    module = load_example("reference/cli/data/snapshot/001.py")
    with module.domain.domain_context():
        yield module


def snapshot_rows(module, aggregate_cls, identifier):
    category = aggregate_cls.meta_.stream_category
    return module.domain.event_store.store._read(f"{category}:snapshot-{identifier}")


def test_create_snapshots_returns_the_number_of_users(example):
    assert example.count == 2


def test_create_all_snapshots_maps_each_aggregate_to_its_count(example):
    assert example.results == {"User": 2, "Order": 1}


def test_each_call_wrote_a_snapshot_of_abc_123(example):
    # create_snapshot, create_snapshots and create_all_snapshots each wrote one.
    rows = snapshot_rows(example, example.User, "abc-123")

    assert len(rows) == 3
    assert {row["data"]["email"] for row in rows} == {"ann@example.com"}


def test_snapshot_of_the_order_holds_its_state(example):
    rows = snapshot_rows(example, example.Order, "ord-1")

    assert [row["data"]["user_id"] for row in rows] == ["abc-123"]


def test_create_snapshot_returns_true(example):
    assert example.domain.create_snapshot(example.User, "abc-123") is True


def test_create_snapshot_of_an_unknown_identifier_raises(example):
    with pytest.raises(ObjectNotFoundError, match="identifier nope does not exist"):
        example.domain.create_snapshot(example.User, "nope")
