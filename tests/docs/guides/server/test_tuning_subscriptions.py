"""The examples on the tuning subscriptions guide behave as the page says."""

import pytest

from protean.exceptions import IncorrectUsageError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_sequential_by_partitions_the_order_stream_by_order_id():
    example = load_example("guides/server/tuning-subscriptions/001.py")
    example.domain.init(traverse=False)

    assert example.OrderHandler.meta_.sequential_by == "order_id"
    assert example.domain._partition_keys == {"shop::order": "order_id"}


def test_each_event_carries_its_order_id_as_the_partition_key():
    example = load_example("guides/server/tuning-subscriptions/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        first = example.place_order(10.0)
        second = example.place_order(20.0)
        rows = example.domain._get_outbox_repo("default").query.all().items

    assert sorted(row.partition_key for row in rows) == sorted([first.id, second.id])


def test_a_key_the_event_does_not_carry_fails_at_init():
    example = load_example("guides/server/tuning-subscriptions/001.py")
    example.OrderHandler.meta_.sequential_by = "customer_id"

    with pytest.raises(IncorrectUsageError, match="sequential_by='customer_id'"):
        example.domain.init(traverse=False)
