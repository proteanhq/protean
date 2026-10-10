"""Check what docs/guides/change-state/temporal-queries.md says.

The page's example writes an event-sourced ``Order``, ``order-123``, with
seven events: version 0 places it, versions 1 to 3 add one item each, and
versions 4 to 6 add two items each. ``cutoff`` falls between versions 3 and 4.
The page's last example adds one more item inside a unit of work but never
saves it, so the order stays at version 6. Each test loads the example fresh, with its own
memory event store.
"""

import pytest

from protean.exceptions import IncorrectUsageError, ObjectNotFoundError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    module = load_example("guides/change-state/temporal-queries/001.py")
    yield module
    module.domain.event_store.store._data_reset()


@pytest.fixture
def repo(example):
    with example.domain.domain_context():
        yield example.domain.repository_for(example.Order)


def test_page_examples_load_the_documented_states(example):
    assert example.order_v5._version == 5
    assert example.order_v5.item_count == 7  # 1 + 1 + 1 + 2 + 2
    assert example.order_v5._is_temporal is True
    assert example.order_then._version == 3
    assert example.order_then.item_count == 3
    assert example.historical._version == 0
    assert example.historical.item_count == 0
    assert example.current.item_count == 10  # the unsaved in-memory change


def test_at_version_returns_the_state_after_that_event(repo):
    order = repo.get("order-123", at_version=5)

    assert order._version == 5
    assert order.item_count == 7
    assert order._is_temporal is True


def test_at_version_zero_is_the_state_after_the_first_event(repo):
    order = repo.get("order-123", at_version=0)

    assert order._version == 0
    assert order.customer == "Alice"
    assert order.item_count == 0


def test_plain_get_returns_the_latest_writable_state(repo):
    order = repo.get("order-123")

    assert order._version == 6
    assert order.item_count == 9  # 3 + 6; the last example's pencil was not saved
    assert order._is_temporal is False


def test_as_of_returns_the_state_at_the_cutoff(example, repo):
    order = repo.get("order-123", as_of=example.cutoff)

    assert order._version == 3
    assert order.item_count == 3
    assert order._is_temporal is True


def test_raise_on_a_current_aggregate_records_the_event(example, repo):
    order = repo.get("order-123")

    order.add_item("eraser", quantity=1)

    assert order.item_count == 10
    assert [type(event) for event in order._events] == [example.ItemAdded]


def test_raise_on_a_temporal_aggregate_is_rejected(example, repo):
    order_v5 = repo.get("order-123", at_version=5)

    with pytest.raises(IncorrectUsageError):
        order_v5.raise_(
            example.ItemAdded(order_id="order-123", product="eraser", quantity=1)
        )
    assert order_v5.item_count == 7


def test_at_version_or_as_of_alone_is_accepted(example, repo):
    assert repo.get("order-123", at_version=5)._version == 5
    assert repo.get("order-123", as_of=example.cutoff)._version == 3


def test_at_version_and_as_of_together_are_rejected(example, repo):
    with pytest.raises(IncorrectUsageError):
        repo.get("order-123", at_version=5, as_of=example.cutoff)


def test_at_version_past_the_latest_names_the_latest_version(repo):
    assert repo.get("order-123", at_version=6)._version == 6

    with pytest.raises(ObjectNotFoundError, match="Latest version is 6"):
        repo.get("order-123", at_version=7)
