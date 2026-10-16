"""Run the examples on ``docs/patterns/thin-handlers-rich-domain.md``."""

from datetime import UTC, date, datetime, timedelta

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example, outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def _in_context(example, event_processing="async"):
    example.domain.config["event_processing"] = event_processing
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def refunds():
    yield from _in_context(
        load_example("patterns/thin-handlers-rich-domain/refunds/domain.py")
    )


@pytest.fixture
def accounts():
    yield from _in_context(load_example("patterns/thin-handlers-rich-domain/001.py"))


@pytest.fixture
def transfers():
    yield from _in_context(load_example("patterns/thin-handlers-rich-domain/002.py"))


@pytest.fixture
def money():
    yield from _in_context(load_example("patterns/thin-handlers-rich-domain/003.py"))


@pytest.fixture
def warehouse():
    yield from _in_context(
        load_example("patterns/thin-handlers-rich-domain/004.py"),
        event_processing="sync",
    )


@pytest.fixture
def ordering():
    yield from _in_context(load_example("patterns/thin-handlers-rich-domain/005.py"))


# --- After: Thin Handler, Rich Aggregate ---


def _saved_order(example, **values):
    order = example.Order(customer_id="cust-1", total=100.0, **values)
    example.domain.repository_for(example.Order).add(order)
    return order


def test_request_refund_command_changes_state_through_the_aggregate(refunds):
    order = _saved_order(
        refunds, status="delivered", delivered_at=datetime.now(UTC) - timedelta(days=3)
    )

    refunds.domain.process(
        refunds.RequestRefund(order_id=order.order_id, amount=40.0, reason="Damaged"),
        asynchronous=False,
    )

    stored = refunds.domain.repository_for(refunds.Order).get(order.order_id)
    assert stored.status == "refund_requested"
    assert stored.refund_amount == 40.0
    assert stored.refund_reason == "Damaged"
    assert stored.refund_requested_at is not None


def test_refund_without_amount_returns_what_is_left(refunds):
    order = _saved_order(
        refunds,
        status="delivered",
        partial_refund_amount=30.0,
        delivered_at=datetime.now(UTC),
    )

    refunds.domain.process(
        refunds.RequestRefund(order_id=order.order_id, reason="Changed mind"),
        asynchronous=False,
    )

    stored = refunds.domain.repository_for(refunds.Order).get(order.order_id)
    assert stored.refund_amount == 70.0


def test_refund_raises_refund_requested(refunds):
    order = refunds.Order(
        customer_id="cust-1",
        status="delivered",
        total=100.0,
        delivered_at=datetime.now(UTC),
    )

    order.request_refund(amount=25.0, reason="Late")

    [event] = order._events
    assert isinstance(event, refunds.RefundRequested)
    assert event.order_id == order.order_id
    assert event.customer_id == "cust-1"
    assert event.amount == 25.0
    assert event.reason == "Late"


def test_refund_of_shipped_order_intercepts_the_shipment(refunds):
    order = refunds.Order(
        customer_id="cust-1", status="shipped", total=100.0, tracking_number="TRK-9"
    )

    order.request_refund(reason="Changed mind")

    assert [type(event) for event in order._events] == [
        refunds.RefundRequested,
        refunds.ShipmentInterceptRequested,
    ]
    assert order._events[1].tracking_number == "TRK-9"


def test_refund_of_draft_order_is_rejected_and_order_is_unchanged(refunds):
    order = _saved_order(refunds, status="draft")

    with pytest.raises(ValidationError) as exc:
        order.request_refund(reason="Changed mind")

    assert exc.value.messages == {
        "status": ["Only shipped or delivered orders can be refunded"]
    }
    assert order.status == "draft"
    assert order.refund_amount is None
    assert order._events == []


def test_refund_command_for_draft_order_leaves_stored_order_unchanged(refunds):
    order = _saved_order(refunds, status="draft")

    with pytest.raises(ValidationError) as exc:
        refunds.domain.process(
            refunds.RequestRefund(order_id=order.order_id, reason="Changed mind"),
            asynchronous=False,
        )

    assert exc.value.messages == {
        "status": ["Only shipped or delivered orders can be refunded"]
    }
    stored = refunds.domain.repository_for(refunds.Order).get(order.order_id)
    assert stored.status == "draft"
    assert stored.refund_amount is None


def test_refund_after_window_is_rejected_and_order_is_unchanged(refunds):
    order = refunds.Order(
        customer_id="cust-1",
        status="delivered",
        total=100.0,
        delivered_at=datetime.now(UTC) - timedelta(days=31),
    )

    with pytest.raises(ValidationError) as exc:
        order.request_refund(reason="Changed mind")

    assert exc.value.messages == {"timing": ["Refund window has expired (30 days)"]}
    assert order.status == "delivered"
    assert order.refund_amount is None
    assert order._events == []


def test_thin_handler_tests_pass():
    result = run_example_tests("patterns/thin-handlers-rich-domain/test_refund.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 5}


# --- Aggregate Methods: Single-Aggregate Business Rules ---


def _account(example, **values):
    account = example.Account(**values)
    example.domain.repository_for(example.Account).add(account)
    return account


def test_withdraw_command_debits_the_stored_account(accounts):
    account = _account(accounts, balance=1000.0)

    accounts.domain.process(
        accounts.WithdrawMoney(account_id=account.account_id, amount=300.0),
        asynchronous=False,
    )

    stored = accounts.domain.repository_for(accounts.Account).get(account.account_id)
    assert stored.balance == 700.0
    assert stored.daily_withdrawal_total == 300.0
    assert stored.last_withdrawal_date == date.today()


def test_withdraw_raises_money_withdrawn(accounts):
    account = accounts.Account(balance=1000.0)

    account.withdraw(250.0)

    [event] = account._events
    assert isinstance(event, accounts.MoneyWithdrawn)
    assert event.amount == 250.0
    assert event.new_balance == 750.0


def test_withdraw_may_use_the_overdraft(accounts):
    account = accounts.Account(balance=100.0, overdraft_limit=50.0)

    account.withdraw(150.0)

    assert account.balance == -50.0


def test_daily_total_adds_up_on_the_same_day(accounts):
    account = accounts.Account(balance=10000.0)

    account.withdraw(3000.0)
    account.withdraw(1500.0)

    assert account.daily_withdrawal_total == 4500.0


def test_daily_total_restarts_on_a_new_day(accounts):
    account = accounts.Account(
        balance=10000.0,
        daily_withdrawal_total=4900.0,
        last_withdrawal_date=date.today() - timedelta(days=1),
    )

    account.withdraw(1000.0)

    assert account.daily_withdrawal_total == 1000.0
    assert account.last_withdrawal_date == date.today()


@pytest.mark.parametrize(
    ("values", "amount", "messages"),
    [
        (
            {"balance": 1000.0, "status": "frozen"},
            100.0,
            {"status": ["Cannot withdraw from a non-active account"]},
        ),
        (
            {"balance": 1000.0},
            0.0,
            {"amount": ["Withdrawal amount must be positive"]},
        ),
        (
            {
                "balance": 10000.0,
                "daily_withdrawal_total": 4800.0,
                "last_withdrawal_date": date.today(),
            },
            300.0,
            {"amount": ["Daily withdrawal limit of 5000.0 exceeded"]},
        ),
        (
            {"balance": 100.0, "overdraft_limit": 50.0},
            151.0,
            {"balance": ["Insufficient funds"]},
        ),
    ],
    ids=["non_active", "not_positive", "daily_limit", "insufficient_funds"],
)
def test_withdraw_rule_rejects_and_leaves_stored_account_unchanged(
    accounts, values, amount, messages
):
    account = _account(accounts, **values)

    with pytest.raises(ValidationError) as exc:
        accounts.domain.process(
            accounts.WithdrawMoney(account_id=account.account_id, amount=amount),
            asynchronous=False,
        )

    assert exc.value.messages == messages
    stored = accounts.domain.repository_for(accounts.Account).get(account.account_id)
    assert stored.balance == values["balance"]
    assert stored.daily_withdrawal_total == values.get("daily_withdrawal_total", 0.0)


# --- Value Objects: Concept-Level Logic ---


def test_money_adds_same_currency(money):
    total = money.Money(amount=10.0, currency="USD").add(
        money.Money(amount=5.5, currency="USD")
    )

    assert total == money.Money(amount=15.5, currency="USD")


def test_money_rejects_adding_different_currencies(money):
    usd = money.Money(amount=10.0, currency="USD")

    with pytest.raises(ValidationError) as exc:
        usd.add(money.Money(amount=5.0, currency="EUR"))

    assert exc.value.messages == {"currency": ["Cannot add different currencies"]}
    assert usd == money.Money(amount=10.0, currency="USD")


# --- Event Handlers Follow the Same Pattern ---


def _stock(example, product_id, available):
    example.domain.repository_for(example.Inventory).add(
        example.Inventory(product_id=product_id, available=available)
    )


def _place(example, items):
    order = example.Order(customer_id="cust-1")
    order.raise_(example.OrderPlaced(order_id=order.order_id, items=items))
    example.domain.repository_for(example.Order).add(order)
    return order


def test_order_placed_reserves_inventory_through_the_aggregate(warehouse):
    _stock(warehouse, "prod-1", 5)
    _stock(warehouse, "prod-2", 3)

    order = _place(
        warehouse,
        [
            {"product_id": "prod-1", "quantity": 2},
            {"product_id": "prod-2", "quantity": 3},
        ],
    )

    repo = warehouse.domain.repository_for(warehouse.Inventory)
    first, second = repo.get("prod-1"), repo.get("prod-2")
    assert (first.available, first.reserved) == (3, 2)
    assert (second.available, second.reserved) == (0, 3)
    assert first.reserved_for == [order.order_id]


def test_reserve_twice_for_one_order_reserves_once(warehouse):
    inventory = warehouse.Inventory(product_id="prod-1", available=5)

    inventory.reserve(order_id="ord-1", quantity=2)
    inventory.reserve(order_id="ord-1", quantity=2)

    assert (inventory.available, inventory.reserved) == (3, 2)


def test_reserve_more_than_available_is_rejected_and_stock_is_unchanged(warehouse):
    inventory = warehouse.Inventory(product_id="prod-1", available=1)

    with pytest.raises(ValidationError) as exc:
        inventory.reserve(order_id="ord-1", quantity=2)

    assert exc.value.messages == {"quantity": ["Only 1 units of prod-1 left"]}
    assert (inventory.available, inventory.reserved) == (1, 0)
    assert inventory.reserved_for == []


# --- Application Services Follow the Same Pattern ---


def test_place_order_use_case_stores_a_placed_order(ordering):
    ordering.OrderApplicationService().place_order(
        order_id="ord-1",
        customer_id="cust-1",
        items=[{"product_id": "prod-1", "quantity": 2, "unit_price": 10.0}],
        total=20.0,
        currency="USD",
    )

    stored = ordering.domain.repository_for(ordering.Order).get("ord-1")
    assert stored.status == "placed"
    assert stored.total == ordering.Money(amount=20.0, currency="USD")
    assert [(i.product_id, i.quantity) for i in stored.items] == [("prod-1", 2)]


def test_place_order_without_items_is_rejected_and_nothing_is_stored(ordering):
    with pytest.raises(ValidationError) as exc:
        ordering.OrderApplicationService().place_order(
            order_id="ord-1", customer_id="cust-1", items=[], total=0.0, currency="USD"
        )

    assert exc.value.messages == {"items": ["Cannot place an order with no items"]}
    assert ordering.domain.repository_for(ordering.Order).query.all().items == []


# --- Domain Services: Cross-Aggregate Coordination ---


def _transfer(transfers, *, balance=1000.0, risk_score=2.0, amount=300.0):
    policy = transfers.CreditPolicy(max_transfer_amount=500.0, max_risk_score=5.0)
    source = transfers.Account(
        balance=balance, risk_score=risk_score, credit_policy_id=policy.policy_id
    )
    transfers.domain.repository_for(transfers.CreditPolicy).add(policy)
    transfers.domain.repository_for(transfers.Account).add(source)

    transfers.domain.process(
        transfers.TransferMoney(
            transfer_id="txn-1",
            from_account_id=source.account_id,
            to_account_id="acc-2",
            amount=amount,
        ),
        asynchronous=False,
    )
    return source


def test_transfer_debits_the_source_through_the_aggregate(transfers):
    source = _transfer(transfers)

    stored = transfers.domain.repository_for(transfers.Account).get(source.account_id)
    assert stored.balance == 700.0


@pytest.mark.parametrize(
    "values, messages",
    [
        ({"amount": 600.0}, {"amount": ["Exceeds policy limit of 500.0"]}),
        (
            {"risk_score": 8.0},
            {"risk": ["Account risk score exceeds policy threshold"]},
        ),
        ({"balance": 100.0}, {"balance": ["Insufficient funds"]}),
    ],
    ids=["policy_limit", "risk_score", "insufficient_funds"],
)
def test_transfer_that_breaks_a_rule_leaves_the_balance_unchanged(
    transfers, values, messages
):
    balance = values.get("balance", 1000.0)
    with pytest.raises(ValidationError) as exc:
        _transfer(transfers, **values)

    assert exc.value.messages == messages
    [stored] = transfers.domain.repository_for(transfers.Account).query.all().items
    assert stored.balance == balance
