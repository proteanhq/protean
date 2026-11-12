"""`view_for` on a cache-backed projection reads keys the service builds.

Runs on every adapter in `CACHE_CONFIGS`, so a key `add` writes is the key
`view_for(...).get` and `view_for(...).count` read on memory and on Redis.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, String

from .conftest import CACHE_CONFIGS


class OrderSummary(BaseProjection):
    order_id: Identifier(identifier=True)
    status: String(required=True)


@pytest.fixture(params=CACHE_CONFIGS)
def domain(request):
    domain = Domain(name="Test")
    domain.config["caches"]["default"] = request.param
    domain.register(OrderSummary, cache="default")
    domain.init(traverse=False)

    with domain.domain_context():
        cache = domain.cache_for(OrderSummary)
        cache.clear()
        yield domain
        cache.clear()
        cache._close()


@pytest.fixture
def seeded(domain):
    cache = domain.cache_for(OrderSummary)
    cache.add(OrderSummary(order_id="ord-1", status="placed"))
    cache.add(OrderSummary(order_id="ord-2", status="shipped"))


class TestAReadViewOverACache:
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
