"""Tests for the @read decorator used in QueryHandler classes."""

import pytest

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.fields import Float, Identifier, String
from protean.utils.mixins import read


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total_amount = Float()


class GetOrdersByCustomer(BaseQuery):
    customer_id = Identifier(required=True)


class GetOrderById(BaseQuery):
    order_id = Identifier(required=True)


class OrderSummaryQueryHandler(BaseQueryHandler):
    @read(GetOrdersByCustomer)
    def get_by_customer(self, query):
        return [{"order_id": "1", "customer_id": query.customer_id}]

    @read(GetOrderById)
    def get_by_id(self, query):
        return {"order_id": query.order_id, "status": "shipped"}


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(OrderSummary)
    test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
    test_domain.register(GetOrderById, part_of=OrderSummary)
    test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
    test_domain.init(traverse=False)


class TestReadDecoratorMetadata:
    def test_read_sets_target_cls(self):
        """The @read decorator should set _target_cls on the wrapper."""

        @read(GetOrdersByCustomer)
        def sample_handler(self, query):
            return []

        assert hasattr(sample_handler, "_target_cls")
        assert sample_handler._target_cls == GetOrdersByCustomer

    def test_read_preserves_function_name(self):
        """The @read decorator should preserve the original function name."""

        @read(GetOrdersByCustomer)
        def my_handler(self, query):
            return []

        assert my_handler.__name__ == "my_handler"


class TestReadDecoratorRouting:
    def test_handler_map_is_populated(self):
        """After domain.init(), the _handlers map should have entries."""
        assert len(OrderSummaryQueryHandler._handlers) > 0

    def test_handler_map_contains_query_types(self):
        """The _handlers map should contain the query __type__ keys."""
        handler_keys = set(OrderSummaryQueryHandler._handlers.keys())
        assert GetOrdersByCustomer.__type__ in handler_keys
        assert GetOrderById.__type__ in handler_keys

    def test_handler_method_is_callable(self):
        """Handler methods in the map should be callable."""
        query_type = GetOrdersByCustomer.__type__
        handler_methods = OrderSummaryQueryHandler._handlers[query_type]
        assert len(handler_methods) == 1
        handler_method = next(iter(handler_methods))
        assert callable(handler_method)

    def test_handle_routes_to_correct_method(self):
        """_handle() should route to the correct handler method."""
        query = GetOrdersByCustomer(customer_id="cust-123")
        result = OrderSummaryQueryHandler._handle(query)

        assert isinstance(result, list)
        assert result[0]["customer_id"] == "cust-123"

    def test_handle_routes_different_queries(self):
        """Different queries should route to different handler methods."""
        result1 = OrderSummaryQueryHandler._handle(
            GetOrdersByCustomer(customer_id="cust-1")
        )
        result2 = OrderSummaryQueryHandler._handle(GetOrderById(order_id="order-1"))

        assert isinstance(result1, list)
        assert isinstance(result2, dict)
        assert result2["order_id"] == "order-1"
