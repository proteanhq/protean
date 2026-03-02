"""Tests for QueryProcessor — the extracted query dispatch logic.

These tests exercise the ``QueryProcessor`` directly through the Domain's
``dispatch()`` method (which delegates to ``self._query_processor.dispatch()``)
as well as the ``handler_for()`` lookup, verifying that the extraction from
the monolithic Domain class is correct.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.exceptions import IncorrectUsageError
from protean.fields import Float, Identifier, String
from protean.utils.mixins import read


# ─── Shared domain elements ─────────────────────────────────────────────


class OrderSummary(BaseProjection):
    order_id: Identifier(identifier=True)
    customer_name: String(max_length=100)
    status: String(max_length=20)
    total_amount: Float()


class GetOrdersByCustomer(BaseQuery):
    customer_id: Identifier(required=True)


class GetOrderById(BaseQuery):
    order_id: Identifier(required=True)


class OrderSummaryQueryHandler(BaseQueryHandler):
    @read(GetOrdersByCustomer)
    def get_by_customer(self, query: GetOrdersByCustomer):
        return [
            {
                "order_id": "order-1",
                "customer_id": query.customer_id,
                "status": "shipped",
            },
            {
                "order_id": "order-2",
                "customer_id": query.customer_id,
                "status": "pending",
            },
        ]

    @read(GetOrderById)
    def get_by_id(self, query: GetOrderById):
        return {"order_id": query.order_id, "status": "shipped"}


# ─── Dispatch Tests ─────────────────────────────────────────────────────


class TestQueryProcessorDispatch:
    """Verify that QueryProcessor.dispatch() routes queries to their handlers."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.register(GetOrderById, part_of=OrderSummary)
        test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
        test_domain.init(traverse=False)

    def test_dispatch_routes_query_to_handler_and_returns_result(self, test_domain):
        """dispatch() should route a query to the correct handler method
        and return the handler's return value."""
        result = test_domain.dispatch(GetOrdersByCustomer(customer_id="cust-42"))

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(r["customer_id"] == "cust-42" for r in result)

    def test_dispatch_rejects_non_query_object(self, test_domain):
        """dispatch() should raise IncorrectUsageError for non-Query objects."""
        with pytest.raises(IncorrectUsageError, match="is not a Query"):
            test_domain.dispatch("not a query")

    def test_dispatch_rejects_unregistered_query(self, test_domain):
        """dispatch() should raise IncorrectUsageError for a query class
        that was never registered with the domain."""

        class OrphanQuery(BaseQuery):
            value: String()

        with pytest.raises(IncorrectUsageError, match="is not registered"):
            test_domain.dispatch(OrphanQuery(value="test"))

    def test_dispatch_rejects_query_without_handler(self, test_domain):
        """dispatch() should raise IncorrectUsageError when a registered query
        has no handler method mapped to it."""

        class ProductCatalog(BaseProjection):
            product_id: Identifier(identifier=True)
            name: String(max_length=200)

        class SearchProducts(BaseQuery):
            keyword: String(required=True)

        # Register the query but *not* any handler that handles it.
        test_domain.register(ProductCatalog)
        test_domain.register(SearchProducts, part_of=ProductCatalog)
        test_domain.init(traverse=False)

        with pytest.raises(IncorrectUsageError, match="No Query Handler registered"):
            test_domain.dispatch(SearchProducts(keyword="widgets"))


# ─── handler_for Tests ──────────────────────────────────────────────────


class TestQueryProcessorHandlerFor:
    """Verify that QueryProcessor.handler_for() resolves handlers correctly."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
        test_domain.register(GetOrderById, part_of=OrderSummary)
        test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
        test_domain.init(traverse=False)

    def test_handler_for_returns_handler_class(self, test_domain):
        """handler_for() should return the QueryHandler class that handles
        the given query, or None when no handler is registered."""
        query = GetOrdersByCustomer(customer_id="cust-1")
        handler_cls = test_domain._query_processor.handler_for(query)

        assert handler_cls is OrderSummaryQueryHandler

    def test_handler_for_returns_none_when_no_handler(self, test_domain):
        """handler_for() should return None for a query with no handler."""

        class ProductCatalog(BaseProjection):
            product_id: Identifier(identifier=True)
            name: String(max_length=200)

        class SearchProducts(BaseQuery):
            keyword: String(required=True)

        test_domain.register(ProductCatalog)
        test_domain.register(SearchProducts, part_of=ProductCatalog)
        test_domain.init(traverse=False)

        handler_cls = test_domain._query_processor.handler_for(
            SearchProducts(keyword="widgets")
        )
        assert handler_cls is None
