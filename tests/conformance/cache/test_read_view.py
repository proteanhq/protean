"""`view_for` on a cache-backed projection reads keys the service builds.

A key `add` writes is the key `view_for(...).get` and `view_for(...).count`
read on the adapter under test.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, String
from protean.port.cache import CacheCapabilities


class OrderSummary(BaseProjection):
    order_id: Identifier(identifier=True)
    status: String(required=True)


class CustomerSummary(BaseProjection):
    customer_id: Identifier(identifier=True)
    name: String(required=True)


@pytest.fixture
def domain(test_domain):
    test_domain.register(OrderSummary, cache="default")
    test_domain.register(CustomerSummary, cache="default")
    return test_domain


@pytest.fixture
def seeded(domain):
    cache = domain.cache_for(OrderSummary)
    cache.add(OrderSummary(order_id="ord-1", status="placed"))
    cache.add(OrderSummary(order_id="ord-2", status="shipped"))
    # Another projection's entry in the same cache, which `count` must skip.
    cache.add(CustomerSummary(customer_id="cus-1", name="Ada"))


@pytest.mark.requires(CacheCapabilities.KEY_VALUE)
class TestAReadViewOverACache:
    @pytest.mark.requires(CacheCapabilities.PATTERN_MATCH)
    def test_count_counts_the_projection_s_entries(self, domain, seeded):
        assert domain.view_for(OrderSummary).count() == 2

    def test_get_returns_the_entry_under_key_for(self, domain, seeded):
        summary = domain.view_for(OrderSummary).get("ord-2")

        assert (summary.order_id, summary.status) == ("ord-2", "shipped")

    def test_get_of_a_missing_identifier_is_not_found(self, domain, seeded):
        with pytest.raises(ObjectNotFoundError):
            domain.view_for(OrderSummary).get("ord-9")

    def test_the_entry_lives_under_key_for(self, domain, seeded):
        cache = domain.cache_for(OrderSummary)

        assert cache.get(cache.key_for(OrderSummary, "ord-1")) == OrderSummary(
            order_id="ord-1", status="placed"
        )
