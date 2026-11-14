"""The `Cache` service builds every key and pattern for a projection."""

import pytest

from protean.core.projection import BaseProjection
from protean.fields import Identifier, Integer, String


class OrderSummary(BaseProjection):
    order_id: Identifier(identifier=True)
    total: Integer()


class P(BaseProjection):
    key: Identifier(identifier=True)
    name: String()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(OrderSummary, cache="default")
    test_domain.register(P, cache="default")
    test_domain.init(traverse=False)


class TestKeyFor:
    def test_the_key_is_the_snake_case_name_then_the_identifier(self, test_domain):
        cache = test_domain.cache_for(OrderSummary)

        assert cache.key_for(OrderSummary, "ord-1") == "order_summary:::ord-1"

    def test_a_one_letter_name_lowercases(self, test_domain):
        assert test_domain.cache_for(P).key_for(P, "1") == "p:::1"

    def test_a_non_string_identifier_is_formatted_with_str(self, test_domain):
        assert test_domain.cache_for(P).key_for(P, 7) == "p:::7"


class TestPatternFor:
    def test_the_pattern_is_the_snake_case_name_then_a_glob(self, test_domain):
        cache = test_domain.cache_for(OrderSummary)

        assert cache.pattern_for(OrderSummary) == "order_summary:::*"

    def test_a_one_letter_name_lowercases(self, test_domain):
        assert test_domain.cache_for(P).pattern_for(P) == "p:::*"


class TestAddAndCallersShareTheKey:
    def test_an_added_projection_is_read_back_under_key_for(self, test_domain):
        cache = test_domain.cache_for(OrderSummary)
        summary = OrderSummary(order_id="ord-1", total=40)

        cache.add(summary)

        assert cache.get(cache.key_for(OrderSummary, "ord-1")) == summary

    def test_remove_deletes_the_entry_under_key_for(self, test_domain):
        cache = test_domain.cache_for(OrderSummary)
        summary = OrderSummary(order_id="ord-1", total=40)
        cache.add(summary)
        key = cache.key_for(OrderSummary, "ord-1")
        assert cache.get(key) is not None

        cache.remove(summary)

        assert cache.get(key) is None

    def test_pattern_for_counts_only_the_projection_s_entries(self, test_domain):
        cache = test_domain.cache_for(OrderSummary)
        cache.add(OrderSummary(order_id="ord-1", total=40))
        cache.add(OrderSummary(order_id="ord-2", total=10))
        cache.add(P(key="1", name="other"))

        assert cache.count(cache.pattern_for(OrderSummary)) == 2
