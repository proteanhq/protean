# Test that limit provided in Aggregate options is respected

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Date


class Order(BaseAggregate):
    ordered_on = Date()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)


def test_entity_query_limit_is_100_by_default(test_domain):
    test_domain.register(Order)

    assert Order.meta_.limit == 100


def test_entity_query_limit_can_be_explicitly_set_in_entity_config(test_domain):
    test_domain.register(Order, limit=500)

    assert Order.meta_.limit == 500


def test_entity_query_limit_can_be_unlimited(test_domain):
    test_domain.register(Order, limit=None)

    assert Order.meta_.limit is None


def test_entity_query_limit_is_unlimited_when_limit_is_set_to_negative_value(
    test_domain,
):
    test_domain.register(Order, limit=-1)

    assert Order.meta_.limit is None
