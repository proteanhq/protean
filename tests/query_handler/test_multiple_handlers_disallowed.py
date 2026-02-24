"""Tests verifying that a query cannot be handled by multiple handlers."""

import pytest

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.exceptions import NotSupportedError
from protean.fields import Float, Identifier, String
from protean.utils.mixins import read


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total_amount = Float()


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)


class TestMultipleHandlersDisallowed:
    def test_two_methods_for_same_query_in_one_handler(self, test_domain):
        """Two methods in the same handler targeting the same query should raise."""
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)

        class DuplicateHandler(BaseQueryHandler):
            @read(GetOrdersByCustomer)
            def method_one(self, query):
                return []

            @read(GetOrdersByCustomer)
            def method_two(self, query):
                return []

        test_domain.register(DuplicateHandler, part_of=OrderSummary)

        with pytest.raises(
            NotSupportedError,
            match="cannot be handled by multiple handlers",
        ):
            test_domain.init(traverse=False)
