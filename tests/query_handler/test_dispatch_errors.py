"""Tests for domain.dispatch() error handling."""

import pytest

from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.exceptions import IncorrectUsageError
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
        return []


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(OrderSummary)
    test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
    test_domain.register(GetOrderById, part_of=OrderSummary)
    test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
    test_domain.init(traverse=False)


class TestDispatchErrors:
    def test_dispatch_non_query_raises_error(self, test_domain):
        """Dispatching a non-Query object should raise IncorrectUsageError."""
        with pytest.raises(IncorrectUsageError, match="is not a Query"):
            test_domain.dispatch("not a query")

    def test_dispatch_non_query_dict_raises_error(self, test_domain):
        """Dispatching a dict should raise IncorrectUsageError."""
        with pytest.raises(IncorrectUsageError, match="is not a Query"):
            test_domain.dispatch({"customer_id": "123"})

    def test_dispatch_unregistered_query_raises_error(self, test_domain):
        """Dispatching an unregistered query should raise IncorrectUsageError."""

        class UnregisteredQuery(BaseQuery):
            value = String()

        with pytest.raises(
            IncorrectUsageError,
            match="is not registered",
        ):
            test_domain.dispatch(UnregisteredQuery(value="test"))

    def test_dispatch_query_with_no_handler_raises_error(self, test_domain):
        """Dispatching a query with no registered handler should raise error."""
        # GetOrderById is registered but has no handler method
        with pytest.raises(
            IncorrectUsageError,
            match="No Query Handler registered",
        ):
            test_domain.dispatch(GetOrderById(order_id="order-1"))
