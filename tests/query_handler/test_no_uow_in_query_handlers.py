"""Tests verifying that query handlers do NOT wrap execution in UnitOfWork.

This is the inverse of tests/command_handler/test_uow_around_command_handlers.py
which verifies that command handlers DO wrap in UoW.
"""

import mock
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


def dummy(*args):
    pass


class OrderSummaryQueryHandler(BaseQueryHandler):
    @read(GetOrdersByCustomer)
    def get_by_customer(self, query):
        dummy(self, query)
        return [{"customer_id": query.customer_id}]


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(OrderSummary)
    test_domain.register(GetOrdersByCustomer, part_of=OrderSummary)
    test_domain.register(OrderSummaryQueryHandler, part_of=OrderSummary)
    test_domain.init(traverse=False)


@mock.patch("protean.core.unit_of_work.UnitOfWork.__enter__")
@mock.patch("protean.core.unit_of_work.UnitOfWork.__exit__")
def test_uow_is_not_invoked_in_query_handler(mock_exit, mock_enter):
    """Verify that UnitOfWork is NOT created when a query handler executes."""
    query = GetOrdersByCustomer(customer_id="cust-123")
    result = OrderSummaryQueryHandler._handle(query)

    # UoW should NOT have been entered or exited
    mock_enter.assert_not_called()
    mock_exit.assert_not_called()

    # Handler should still return results
    assert result == [{"customer_id": "cust-123"}]


@mock.patch("tests.query_handler.test_no_uow_in_query_handlers.dummy")
def test_handler_method_is_called_directly(mock_dummy):
    """Verify the handler method is called without UoW wrapping."""
    query = GetOrdersByCustomer(customer_id="cust-456")

    handler_obj = OrderSummaryQueryHandler()
    handler_obj.get_by_customer(query)

    mock_dummy.assert_called_once()
    # Verify it was called with the handler instance and query
    call_args = mock_dummy.call_args
    assert call_args[0][1] == query
