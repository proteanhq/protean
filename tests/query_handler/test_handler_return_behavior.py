"""Tests verifying that query handler return values pass through correctly."""

import pytest

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.fields import Float, Identifier, String
from protean.utils.mixins import read


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    status = String(max_length=20)
    total_amount = Float()


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)


class GetOrderCount(BaseQuery):
    customer_id = Identifier(required=True)


class GetOrderById(BaseQuery):
    order_id = Identifier(required=True)


class OrderSummaryQueryHandler(BaseQueryHandler):
    @read(GetOrdersByCustomer)
    def get_by_customer(self, query):
        return [
            {"order_id": "order-1", "customer_id": query.customer_id},
            {"order_id": "order-2", "customer_id": query.customer_id},
        ]

    @read(GetOrderCount)
    def get_count(self, query):
        return 42

    @read(GetOrderById)
    def get_by_id(self, query):
        return None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(OrderSummary)
    test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
    test_domain.register(GetOrderCount, part_of=OrderSummary)
    test_domain.register(GetOrderById, part_of=OrderSummary)
    test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
    test_domain.init(traverse=False)


class TestReturnValuePassThrough:
    def test_list_return_value(self):
        """Handler returning a list should pass through _handle()."""
        result = OrderSummaryQueryHandler._handle(
            GetOrdersByCustomer(customer_id="cust-1")
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["customer_id"] == "cust-1"

    def test_integer_return_value(self):
        """Handler returning an integer should pass through _handle()."""
        result = OrderSummaryQueryHandler._handle(GetOrderCount(customer_id="cust-1"))
        assert result == 42

    def test_none_return_value(self):
        """Handler returning None should pass through _handle()."""
        result = OrderSummaryQueryHandler._handle(GetOrderById(order_id="nonexistent"))
        assert result is None

    def test_return_value_passes_through_dispatch(self, test_domain):
        """Handler return value should pass through domain.dispatch()."""
        result = test_domain.dispatch(GetOrdersByCustomer(customer_id="cust-1"))
        assert isinstance(result, list)
        assert len(result) == 2

    def test_dispatch_returns_integer(self, test_domain):
        """domain.dispatch() should return integer from handler."""
        result = test_domain.dispatch(GetOrderCount(customer_id="cust-1"))
        assert result == 42

    def test_dispatch_returns_none(self, test_domain):
        """domain.dispatch() should return None from handler."""
        result = test_domain.dispatch(GetOrderById(order_id="nonexistent"))
        assert result is None
