"""Runtime behavior of typed queries (``BaseQuery[Result]``).

Declaring a query's result type is a typing-only addition: a
``BaseQuery[Result]`` subclass registers, instantiates, and dispatches
identically to a bare ``BaseQuery`` subclass. These tests pin that down at
runtime so the generic base can never quietly change behavior.
"""

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.fields import Identifier, String
from protean.utils.mixins import read


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    status = String(max_length=20)


class GetTypedOrder(BaseQuery[OrderSummary]):
    order_id = Identifier(required=True)


class GetUntypedOrder(BaseQuery):
    order_id = Identifier(required=True)


class OrderSummaryQueryHandler(BaseQueryHandler):
    @read(GetTypedOrder)
    def get_typed(self, query):
        # GetTypedOrder declares OrderSummary as its result, so the handler
        # returns one. The declaration is phantom at runtime; keeping the two
        # sides in step is the domain author's job.
        return OrderSummary(order_id=query.order_id, status="shipped")

    @read(GetUntypedOrder)
    def get_untyped(self, query):
        return {"order_id": query.order_id, "status": "pending"}


def _register(test_domain):
    test_domain.register(OrderSummary)
    test_domain.register(GetTypedOrder, part_of=OrderSummary)
    test_domain.register(GetUntypedOrder, part_of=OrderSummary)
    test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
    test_domain.init(traverse=False)


class TestTypedQueryRuntime:
    def test_typed_query_has_declared_fields(self):
        """A BaseQuery[Result] subclass builds the same fields as a bare one."""
        assert list(GetTypedOrder.model_fields) == ["order_id"]
        assert list(GetUntypedOrder.model_fields) == ["order_id"]
        assert list(GetTypedOrder.__container_fields__) == ["order_id"]
        assert list(GetUntypedOrder.__container_fields__) == ["order_id"]

    def test_typed_query_instantiates(self):
        """A parametrized subclass instantiates and exposes its payload."""
        query = GetTypedOrder(order_id="order-1")
        assert query.order_id == "order-1"
        assert query.payload == {"order_id": "order-1"}

    def test_typed_query_dispatches(self, test_domain):
        """A typed query dispatches exactly like a bare query."""
        _register(test_domain)

        typed_result = test_domain.dispatch(GetTypedOrder(order_id="order-1"))
        untyped_result = test_domain.dispatch(GetUntypedOrder(order_id="order-2"))

        assert isinstance(typed_result, OrderSummary)
        assert typed_result.order_id == "order-1"
        assert typed_result.status == "shipped"
        assert untyped_result == {"order_id": "order-2", "status": "pending"}
