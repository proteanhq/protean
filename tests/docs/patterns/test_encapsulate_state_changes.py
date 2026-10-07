"""Run the examples on ``docs/patterns/encapsulate-state-changes.md``."""

import subprocess
import sys

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import DOCS_SRC, REPO_ROOT, load_example

pytestmark = pytest.mark.no_test_domain


def _in_context(example):
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def orders():
    yield from _in_context(load_example("patterns/encapsulate-state-changes/001.py"))


@pytest.fixture
def accounts():
    yield from _in_context(load_example("patterns/encapsulate-state-changes/002.py"))


@pytest.fixture
def ledger():
    yield from _in_context(load_example("patterns/encapsulate-state-changes/003.py"))


@pytest.fixture
def restructure():
    yield from _in_context(load_example("patterns/encapsulate-state-changes/004.py"))


@pytest.fixture
def placement():
    yield from _in_context(load_example("patterns/encapsulate-state-changes/005.py"))


@pytest.fixture
def addresses():
    yield from _in_context(load_example("patterns/encapsulate-state-changes/006.py"))


def _order(example, status, with_items=True):
    items = (
        [example.OrderItem(product_id="prod-1", quantity=2, unit_price=10.0)]
        if with_items
        else []
    )
    return example.Order(customer_id="cust-1", items=items, status=status, total=20.0)


def _payload(event):
    data = event.to_dict()
    data.pop("_metadata")
    return data


# Order.ship / cancel / pay (001.py)


def test_ship_sets_shipping_fields_and_raises_order_shipped(orders):
    order = _order(orders, "paid")

    order.ship("TRK-123")

    assert order.status == "shipped"
    assert order.tracking_number == "TRK-123"
    assert order.shipped_at is not None
    assert len(order._events) == 1
    assert isinstance(order._events[0], orders.OrderShipped)
    assert _payload(order._events[0]) == {
        "order_id": order.order_id,
        "customer_id": "cust-1",
        "tracking_number": "TRK-123",
    }


@pytest.mark.parametrize("status", ["draft", "shipped", "cancelled"])
def test_ship_refuses_an_unpaid_order(orders, status):
    order = _order(orders, status)

    with pytest.raises(ValidationError) as exc:
        order.ship("TRK-123")

    assert exc.value.messages == {"status": ["Only paid orders can be shipped"]}
    assert order.status == status
    assert order.tracking_number is None
    assert order.shipped_at is None
    assert order._events == []


def test_ship_refuses_an_order_with_no_items(orders):
    order = _order(orders, "paid", with_items=False)

    with pytest.raises(ValidationError) as exc:
        order.ship("TRK-123")

    assert exc.value.messages == {"items": ["Cannot ship an order with no items"]}
    assert order.status == "paid"
    assert order._events == []


@pytest.mark.parametrize("status", ["draft", "paid"])
def test_cancel_sets_cancellation_fields_and_raises_order_cancelled(orders, status):
    order = _order(orders, status)

    order.cancel("Changed my mind")

    assert order.status == "cancelled"
    assert order.cancellation_reason == "Changed my mind"
    assert order.cancelled_at is not None
    assert len(order._events) == 1
    assert isinstance(order._events[0], orders.OrderCancelled)
    assert _payload(order._events[0]) == {
        "order_id": order.order_id,
        "customer_id": "cust-1",
        "reason": "Changed my mind",
    }


@pytest.mark.parametrize("status", ["shipped", "cancelled"])
def test_cancel_refuses_a_shipped_or_cancelled_order(orders, status):
    order = _order(orders, status)

    with pytest.raises(ValidationError) as exc:
        order.cancel("Too late")

    assert exc.value.messages == {
        "status": ["Cannot cancel a shipped or already cancelled order"]
    }
    assert order.status == status
    assert order.cancellation_reason is None
    assert order._events == []


def test_pay_marks_a_draft_order_paid_and_raises_order_paid(orders):
    order = _order(orders, "draft")

    order.pay()

    assert order.status == "paid"
    assert len(order._events) == 1
    assert isinstance(order._events[0], orders.OrderPaid)
    assert _payload(order._events[0]) == {
        "order_id": order.order_id,
        "customer_id": "cust-1",
        "total": 20.0,
    }


@pytest.mark.parametrize("status", ["paid", "shipped", "cancelled"])
def test_pay_refuses_an_order_that_is_not_draft(orders, status):
    order = _order(orders, status)

    with pytest.raises(ValidationError) as exc:
        order.pay()

    assert exc.value.messages == {"status": ["Only draft orders can be paid"]}
    assert order.status == status
    assert order._events == []


def test_handlers_load_call_and_save(orders):
    repo = orders.domain.repository_for(orders.Order)
    order = _order(orders, "draft")
    repo.add(order)

    orders.domain.process(orders.PayOrder(order_id=order.order_id), asynchronous=False)
    assert repo.get(order.order_id).status == "paid"

    orders.domain.process(
        orders.ShipOrder(order_id=order.order_id, tracking_number="TRK-9"),
        asynchronous=False,
    )
    shipped = repo.get(order.order_id)
    assert shipped.status == "shipped"
    assert shipped.tracking_number == "TRK-9"

    with pytest.raises(ValidationError) as exc:
        orders.domain.process(
            orders.CancelOrder(order_id=order.order_id, reason="Too late"),
            asynchronous=False,
        )
    assert exc.value.messages == {
        "status": ["Cannot cancel a shipped or already cancelled order"]
    }
    assert repo.get(order.order_id).status == "shipped"


def test_page_tests_pass_under_pytest():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(DOCS_SRC / "patterns/encapsulate-state-changes/001.py"),
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout


# Account with an invariant (002.py)


def test_withdraw_lowers_the_balance_and_raises_money_withdrawn(accounts):
    account = accounts.Account(balance=100.0)

    account.withdraw(30.0)

    assert account.balance == 70.0
    assert len(account._events) == 1
    assert isinstance(account._events[0], accounts.MoneyWithdrawn)
    assert _payload(account._events[0]) == {
        "account_id": account.account_id,
        "amount": 30.0,
        "new_balance": 70.0,
    }


def test_withdraw_may_go_into_the_overdraft(accounts):
    account = accounts.Account(balance=10.0)

    account.withdraw(60.0)

    assert account.balance == -50.0


@pytest.mark.parametrize("amount", [0.0, -5.0])
def test_withdraw_refuses_an_amount_that_is_not_positive(accounts, amount):
    account = accounts.Account(balance=100.0)

    with pytest.raises(ValidationError) as exc:
        account.withdraw(amount)

    assert exc.value.messages == {"amount": ["Withdrawal amount must be positive"]}
    assert account.balance == 100.0
    assert account._events == []


def test_invariant_refuses_a_balance_below_the_overdraft_limit(accounts):
    account = accounts.Account(balance=10.0)

    with pytest.raises(ValidationError) as exc:
        account.withdraw(60.01)

    assert exc.value.messages == {
        "balance": ["Balance cannot be below overdraft limit"]
    }
    assert account._events == []


def test_invariant_catches_a_direct_assignment_too(accounts):
    # "regardless of how it was reached"
    account = accounts.Account(balance=10.0)

    with pytest.raises(ValidationError) as exc:
        account.balance = -100.0

    assert exc.value.messages == {
        "balance": ["Balance cannot be below overdraft limit"]
    }


# Event-sourced Account (003.py)


def test_es_withdraw_raises_money_withdrawn_and_apply_lowers_the_balance(ledger):
    account = ledger.Account.open(100.0)

    account.withdraw(30.0)

    assert account.balance == 70.0
    assert [type(e) for e in account._events] == [
        ledger.AccountOpened,
        ledger.MoneyWithdrawn,
    ]
    assert _payload(account._events[0]) == {
        "account_id": account.account_id,
        "opening_balance": 100.0,
    }
    assert _payload(account._events[1]) == {
        "account_id": account.account_id,
        "amount": 30.0,
    }


@pytest.mark.parametrize(
    ("amount", "messages"),
    [
        (0.0, {"amount": ["Withdrawal amount must be positive"]}),
        (-1.0, {"amount": ["Withdrawal amount must be positive"]}),
        (100.01, {"balance": ["Insufficient funds"]}),
    ],
)
def test_es_withdraw_refuses_bad_amounts(ledger, amount, messages):
    account = ledger.Account.open(100.0)

    with pytest.raises(ValidationError) as exc:
        account.withdraw(amount)

    assert exc.value.messages == messages
    assert account.balance == 100.0
    assert [type(e) for e in account._events] == [ledger.AccountOpened]


def test_es_apply_handlers_replay_the_stream(ledger):
    account = ledger.Account.open(100.0)
    account.withdraw(30.0)
    account.withdraw(20.0)

    rebuilt = ledger.Account.from_events(account._events)
    assert rebuilt.account_id == account.account_id
    assert rebuilt.balance == 50.0

    repo = ledger.domain.repository_for(ledger.Account)
    repo.add(account)
    assert repo.get(account.account_id).balance == 50.0


# atomic_change (004.py)


def _items(*rows):
    return [
        {"product_id": product, "quantity": quantity, "unit_price": price}
        for product, quantity, price in rows
    ]


def test_restructure_order_replaces_items_and_total(restructure):
    order = restructure.Order(
        items=[restructure.OrderItem(product_id="p1", quantity=2, unit_price=5.0)],
        total=10.0,
    )

    order.restructure_order(_items(("p2", 1, 7.0), ("p3", 3, 1.0)), 10.0)

    assert [(i.product_id, i.line_total) for i in order.items] == [
        ("p2", 7.0),
        ("p3", 3.0),
    ]
    assert order.total == 10.0


def test_restructure_order_checks_invariants_when_the_block_ends(restructure):
    order = restructure.Order(
        items=[restructure.OrderItem(product_id="p1", quantity=2, unit_price=5.0)],
        total=10.0,
    )

    with pytest.raises(ValidationError) as exc:
        order.restructure_order(_items(("p2", 1, 7.0)), 99.0)

    assert exc.value.messages == {"total": ["Total must match the order items"]}


def test_without_atomic_change_the_first_step_fails_the_invariant(restructure):
    order = restructure.Order(
        items=[restructure.OrderItem(product_id="p1", quantity=2, unit_price=5.0)],
        total=10.0,
    )

    with pytest.raises(ValidationError) as exc:
        order.items = []

    assert exc.value.messages == {"total": ["Total must match the order items"]}


# defaults() and place() (005.py)


def test_defaults_computes_the_total_from_the_items(placement):
    order = placement.Order(
        items=[
            placement.OrderItem(product_id="p1", quantity=2, unit_price=5.0),
            placement.OrderItem(product_id="p2", quantity=1, unit_price=3.0),
        ]
    )

    assert order.total == 13.0
    assert order.status == "draft"
    assert order._events == []


def test_defaults_keeps_a_total_that_was_given(placement):
    order = placement.Order(
        items=[placement.OrderItem(product_id="p1", quantity=2, unit_price=5.0)],
        total=4.0,
    )

    assert order.total == 4.0


def test_place_sets_status_and_raises_order_placed(placement):
    order = placement.Order(
        items=[placement.OrderItem(product_id="p1", quantity=2, unit_price=5.0)]
    )

    order.place()

    assert order.status == "placed"
    assert order.placed_at is not None
    assert len(order._events) == 1
    assert isinstance(order._events[0], placement.OrderPlaced)
    assert order._events[0].order_id == order.order_id
    assert order._events[0].total == 10.0
    assert order._events[0].placed_at == order.placed_at


# update_shipping_address (006.py)


def _address(example, street):
    return example.ShippingAddress(
        street=street,
        city="Springfield",
        state="IL",
        postal_code="62701",
        country="US",
    )


def test_update_shipping_address_replaces_the_address_on_a_draft(addresses):
    order = addresses.Order(shipping_address=_address(addresses, "1 Elm St"))

    order.update_shipping_address(_address(addresses, "456 Oak Ave"))

    assert order.shipping_address == _address(addresses, "456 Oak Ave")


def test_update_shipping_address_refuses_a_placed_order(addresses):
    order = addresses.Order(
        status="placed", shipping_address=_address(addresses, "1 Elm St")
    )

    with pytest.raises(ValidationError) as exc:
        order.update_shipping_address(_address(addresses, "456 Oak Ave"))

    assert exc.value.messages == {
        "status": ["Cannot change address after order is placed"]
    }
    assert order.shipping_address.street == "1 Elm St"
