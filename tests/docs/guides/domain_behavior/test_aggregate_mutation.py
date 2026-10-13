"""The examples on the aggregate mutation guide behave as the page says."""

from datetime import date

import pytest

from protean.exceptions import InvalidOperationError, ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def banking():
    example = load_example("guides/domain-behavior/002.py")
    example.banking.init(traverse=False)
    with example.banking.domain_context():
        yield example


@pytest.fixture
def orders():
    example = load_example("guides/domain-behavior/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def es_orders():
    example = load_example("guides/domain-behavior/aggregate-mutation/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _account(example):
    return example.Account(account_number="1234", balance=1000.0, overdraft_limit=50.0)


def test_withdraw_updates_the_balance(banking):
    account = _account(banking)

    account.withdraw(500.0)

    assert account.to_dict() == {
        "account_number": "1234",
        "balance": 500.0,
        "overdraft_limit": 50.0,
        "id": account.id,
        "_version": -1,
    }


def test_withdraw_past_the_overdraft_limit_raises_and_keeps_the_balance(banking):
    account = _account(banking)

    with pytest.raises(ValidationError) as exc:
        account.withdraw(1100.0)

    assert exc.value.messages == {
        "_entity": ["Balance cannot be below overdraft limit"]
    }
    assert account.balance == 1000.0


def test_an_identifier_cannot_be_reassigned(banking):
    account = _account(banking)

    with pytest.raises(InvalidOperationError) as exc:
        account.id = "new-id"

    assert str(exc.value) == "Identifiers cannot be changed once set"


def _order(example):
    return example.Order(
        customer_id="1",
        order_date=date.today(),
        total_amount=100.0,
        status="PENDING",
        items=[
            example.OrderItem(product_id="1", quantity=4, price=10.0, subtotal=40.0),
            example.OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
        ],
    )


def test_atomic_change_lets_the_total_and_the_items_change_together(orders):
    order = _order(orders)

    orders.add_third_item(order)

    assert order.total_amount == 120.0
    assert [item.product_id for item in order.items] == ["1", "2", "3"]


def test_confirm_raises_an_event_and_the_apply_handler_sets_the_status(es_orders):
    order = es_orders.Order()

    order.confirm()

    assert order.status == "CONFIRMED"
    assert [type(event) for event in order._events] == [es_orders.OrderConfirmed]
    assert order._events[0].order_id == order.id
