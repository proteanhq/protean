"""The examples on the query handlers guide behave as the page says."""

import pytest

from protean import Domain, handle
from protean.exceptions import (
    IncorrectUsageError,
    ObjectNotFoundError,
    ValidationError,
)
from protean.fields import Identifier, String
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def orders():
    example = load_example("guides/consume-state/query-handlers/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        repo = example.domain.repository_for(example.OrderSummary)
        for order_id, customer_id, status in [
            ("order-1", "cust-123", "shipped"),
            ("order-2", "cust-123", "pending"),
            ("order-3", "cust-456", "shipped"),
        ]:
            repo.add(
                example.OrderSummary(
                    order_id=order_id,
                    customer_id=customer_id,
                    customer_name="Ann",
                    status=status,
                    total_amount=10.0,
                )
            )
        yield example


@pytest.fixture
def typed():
    example = load_example("guides/consume-state/query-handlers/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def test_dispatch_returns_the_customers_orders_with_the_status(orders):
    result = orders.domain.dispatch(
        orders.GetOrdersByCustomer(customer_id="cust-123", status="shipped")
    )

    assert [order.order_id for order in result.items] == ["order-1"]


def test_dispatch_without_a_status_returns_every_order_of_the_customer(orders):
    result = orders.domain.dispatch(orders.GetOrdersByCustomer(customer_id="cust-123"))

    assert sorted(order.order_id for order in result.items) == ["order-1", "order-2"]


def test_dispatch_by_id_returns_the_projection_record(orders):
    order = orders.domain.dispatch(orders.GetOrderById(order_id="order-3"))

    assert isinstance(order, orders.OrderSummary)
    assert order.customer_id == "cust-456"
    assert order.status == "shipped"


def test_the_page_dispatch_returns_only_the_shipped_order():
    example = load_example("guides/consume-state/query-handlers/001.py")

    assert [order.order_id for order in example.result.items] == ["order-1"]
    assert example.result.total == 1


def test_query_defaults_apply(orders):
    query = orders.GetOrdersByCustomer(customer_id="cust-123")

    assert query.page == 1
    assert query.page_size == 20


def test_query_rejects_a_missing_required_field(orders):
    with pytest.raises(ValidationError) as exc:
        orders.GetOrdersByCustomer(status="shipped")

    assert "customer_id" in exc.value.messages


def test_query_cannot_be_changed_after_construction(orders):
    query = orders.GetOrdersByCustomer(customer_id="cust-123")

    with pytest.raises(IncorrectUsageError):
        query.status = "shipped"


def test_typed_dispatch_returns_the_order_summary(typed):
    typed.domain.repository_for(typed.OrderSummary).add(
        typed.OrderSummary(order_id="order-1", status="shipped", total_amount=42.0)
    )

    order = typed.domain.dispatch(typed.GetOrderById(order_id="order-1"))

    assert isinstance(order, typed.OrderSummary)
    assert order.status == "shipped"
    assert order.total_amount == 42.0


def test_the_page_typed_dispatch_returns_the_record_it_wrote(typed):
    assert typed.order.order_id == "order-1"
    assert typed.order.status == "shipped"
    assert typed.order.total_amount == 42.0


def test_dispatch_for_a_missing_record_raises_object_not_found(typed):
    with pytest.raises(ObjectNotFoundError):
        typed.domain.dispatch(typed.GetOrderById(order_id="nonexistent"))


def test_dispatch_of_a_query_with_no_handler_raises_incorrect_usage():
    example = load_example("guides/consume-state/query-handlers/002.py")

    @example.domain.query(part_of=example.OrderSummary)
    class GetOrdersByStatus:
        status = String()

    example.domain.init(traverse=False)

    with (
        example.domain.domain_context(),
        pytest.raises(IncorrectUsageError, match="No Query Handler registered"),
    ):
        example.domain.dispatch(GetOrdersByStatus(status="shipped"))


def test_dispatch_of_an_unregistered_query_raises_incorrect_usage(typed):
    other = Domain(name="Other")

    @other.query(part_of="Report")
    class GetReport:
        report_id = Identifier()

    with pytest.raises(IncorrectUsageError, match="is not registered"):
        typed.domain.dispatch(GetReport(report_id="r-1"))


def test_dispatch_rejects_a_value_that_is_not_a_query(typed):
    with pytest.raises(IncorrectUsageError):
        typed.domain.dispatch({"order_id": "order-1"})


def test_handle_on_a_query_handler_method_fails_at_init():
    example = load_example("guides/consume-state/query-handlers/002.py")

    @example.domain.query_handler(part_of=example.OrderSummary)
    class WrongHandler:
        @handle(example.GetOrderById)
        def get_by_id(self, query):
            return None

    with pytest.raises(IncorrectUsageError, match="@read"):
        example.domain.init(traverse=False)
