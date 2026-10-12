"""The examples on the invariants guide behave as the page says."""

from datetime import date, timedelta

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

TOTAL_MISMATCH = {"_entity": ["Total should be sum of item prices"]}


@pytest.fixture
def orders():
    example = load_example("guides/domain-behavior/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def accounts():
    example = load_example("guides/domain-behavior/invariants/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _items(example, first_quantity=4):
    return [
        example.OrderItem(
            product_id="1",
            quantity=first_quantity,
            price=10.0,
            subtotal=first_quantity * 10.0,
        ),
        example.OrderItem(product_id="2", quantity=3, price=20.0, subtotal=60.0),
    ]


def _order(example, **overrides):
    values = {
        "customer_id": "1",
        "order_date": date.today(),
        "total_amount": 100.0,
        "status": "PENDING",
        "items": _items(example),
    }
    values.update(overrides)
    return example.Order(**values)


def test_a_valid_order_is_created(orders):
    order = _order(orders)

    assert order.total_amount == 100.0
    assert len(order.items) == 2


def test_a_wrong_total_fails_on_initialization(orders):
    with pytest.raises(ValidationError) as exc:
        _order(orders, items=_items(orders, first_quantity=2))

    assert exc.value.messages == TOTAL_MISMATCH


def test_a_pending_order_older_than_30_days_fails(orders):
    with pytest.raises(ValidationError) as exc:
        _order(orders, order_date=date.today() - timedelta(days=31))

    assert exc.value.messages == {
        "_entity": ["Order date must be within the last 30 days if status is PENDING"]
    }


def test_a_pending_order_from_30_days_ago_is_valid(orders):
    order = _order(orders, order_date=date.today() - timedelta(days=30))

    assert order.status == "PENDING"


def test_an_order_without_items_fails(orders):
    with pytest.raises(ValidationError) as exc:
        _order(orders, total_amount=0.0, items=[])

    assert exc.value.messages == {
        "_entity": [
            "Customer ID must be non-null and the order must contain at least one item"
        ]
    }


def test_an_item_with_a_wrong_subtotal_fails(orders):
    with pytest.raises(ValidationError) as exc:
        orders.OrderItem(product_id="1", quantity=2, price=10.0, subtotal=25.0)

    assert exc.value.messages == {
        "_entity": [
            "Quantity must be a positive integer and the subtotal must be correctly calculated"
        ]
    }


def test_changing_the_total_alone_fails_and_is_rolled_back(orders):
    order = _order(orders)

    with pytest.raises(ValidationError) as exc:
        order.total_amount = 140.0

    assert exc.value.messages == TOTAL_MISMATCH
    assert order.total_amount == 100.0


def test_adding_an_item_alone_fails_and_is_rolled_back(orders):
    order = _order(orders)

    with pytest.raises(ValidationError) as exc:
        order.add_items(
            orders.OrderItem(product_id="3", quantity=2, price=10.0, subtotal=20.0)
        )

    assert exc.value.messages == TOTAL_MISMATCH
    assert [item.product_id for item in order.items] == ["1", "2"]


def test_atomic_change_checks_only_the_end_state(orders):
    order = _order(orders)

    orders.add_third_item(order)

    assert order.total_amount == 120.0
    assert [item.product_id for item in order.items] == ["1", "2", "3"]


def test_changing_the_total_alone_fails_on_a_fresh_order(orders):
    order = _order(orders)

    with pytest.raises(ValidationError) as exc:
        order.total_amount = 120.0

    assert exc.value.messages == TOTAL_MISMATCH
    assert order.total_amount == 100.0


def test_the_failure_carries_the_post_invariant_code(orders, capsys):
    order = _order(orders)

    orders.change_total(order)

    code, codes, fix = capsys.readouterr().out.splitlines()
    assert code == "INVARIANT_POST_FAILED"
    assert codes == "['INVARIANT_POST_FAILED']"
    assert fix.startswith("Correct the state so the post-condition holds")


def test_two_failing_invariants_are_reported_together(orders):
    with pytest.raises(ValidationError) as exc:
        _order(orders, customer_id=None, items=_items(orders, first_quantity=2))

    assert sorted(exc.value.messages["_entity"]) == [
        "Customer ID must be non-null and the order must contain at least one item",
        "Total should be sum of item prices",
    ]
    assert exc.value.codes == ["INVARIANT_POST_FAILED"]
    assert exc.value.code == "INVARIANT_POST_FAILED"


def test_a_frozen_account_rejects_a_withdrawal_before_the_change(accounts):
    account = accounts.Account(account_number="A1", balance=100.0)
    account.status = "FROZEN"

    with pytest.raises(ValidationError) as exc:
        account.withdraw(10.0)

    assert exc.value.messages == {"_entity": ["Cannot modify a frozen account"]}
    assert account.balance == 100.0


def test_an_overdraw_is_rolled_back_with_the_changed_flag(accounts):
    account = accounts.Account(account_number="A1", balance=100.0)
    account.state_.mark_saved()

    with pytest.raises(ValidationError) as exc:
        account.withdraw(150.0)

    assert exc.value.messages == {"_entity": ["Insufficient funds"]}
    assert account.balance == 100.0
    assert account.state_.is_changed is False


def test_a_withdrawal_within_the_balance_succeeds(accounts):
    account = accounts.Account(account_number="A1", balance=100.0)

    account.withdraw(40.0)

    assert account.balance == 60.0
