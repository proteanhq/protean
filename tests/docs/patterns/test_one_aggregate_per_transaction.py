"""Run the examples on ``docs/patterns/one-aggregate-per-transaction.md``."""

import pytest

from protean.exceptions import ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _start(example, event_processing="sync"):
    domain = example.domain
    domain.config["event_processing"] = event_processing
    domain.init(traverse=False)
    return domain


# Unit of Work and Domain Events: Order hands off to Inventory with a command


@pytest.fixture
def orders():
    example = load_example("patterns/one-aggregate-per-transaction/001.py")
    domain = _start(example)
    with domain.domain_context():
        domain.repository_for(example.Inventory).add(
            example.Inventory(product_id="p1", available=10)
        )
        domain.repository_for(example.Inventory).add(
            example.Inventory(product_id="p2", available=5)
        )
        yield example


def _place_order(example, order_id="o1"):
    example.domain.process(
        example.PlaceOrder(
            order_id=order_id,
            customer_id="c1",
            items=[
                {"product_id": "p1", "quantity": 3, "price": 2.5},
                {"product_id": "p2", "quantity": 1, "price": 4.0},
            ],
        )
    )


def test_placing_an_order_reserves_stock_through_the_event(orders):
    _place_order(orders)

    order = orders.domain.repository_for(orders.Order).get("o1")
    assert order.status == "placed"
    assert order.total == 11.5

    inventory_repo = orders.domain.repository_for(orders.Inventory)
    first = inventory_repo.get("p1")
    second = inventory_repo.get("p2")
    assert (first.available, first.reserved) == (7, 3)
    assert (second.available, second.reserved) == (4, 1)
    assert first.applied_order_ids == ["o1"]


def test_order_place_raises_order_placed_with_the_items():
    example = load_example("patterns/one-aggregate-per-transaction/001.py")
    domain = _start(example)
    with domain.domain_context():
        order = example.Order(
            order_id="o9",
            customer_id="c9",
            items=[{"product_id": "p1", "quantity": 2, "price": 3.0}],
        )
        order.place()

        [event] = order._events
        assert isinstance(event, example.OrderPlaced)
        assert event.order_id == "o9"
        assert event.customer_id == "c9"
        assert event.items == [{"product_id": "p1", "quantity": 2, "price": 3.0}]
        assert event.total == 6.0


def test_the_order_transaction_alone_leaves_inventory_unchanged():
    example = load_example("patterns/one-aggregate-per-transaction/001.py")
    # No sync event processing: only the order's transaction runs
    domain = _start(example, event_processing="async")
    with domain.domain_context():
        domain.repository_for(example.Inventory).add(
            example.Inventory(product_id="p1", available=10)
        )
        domain.repository_for(example.Inventory).add(
            example.Inventory(product_id="p2", available=5)
        )

        _place_order(example)

        assert domain.repository_for(example.Order).get("o1").status == "placed"
        inventory = domain.repository_for(example.Inventory).get("p1")
        assert (inventory.available, inventory.reserved) == (10, 0)
        assert inventory.applied_order_ids == []


def test_a_repeated_reserve_stock_for_the_same_order_is_skipped(orders):
    _place_order(orders)

    orders.domain.process(
        orders.ReserveStock(order_id="o1", product_id="p1", quantity=3)
    )

    inventory = orders.domain.repository_for(orders.Inventory).get("p1")
    assert (inventory.available, inventory.reserved) == (7, 3)


# The Money Transfer Example


@pytest.fixture
def transfers():
    example = load_example("patterns/one-aggregate-per-transaction/002.py")
    domain = _start(example)
    with domain.domain_context():
        repo = domain.repository_for(example.Account)
        repo.add(example.Account(account_id="a", balance=100.0))
        repo.add(example.Account(account_id="b", balance=10.0))
        yield example


def _transfer(example, amount):
    example.domain.process(
        example.TransferMoney(
            transfer_id="t1", from_account_id="a", to_account_id="b", amount=amount
        )
    )


def test_transfer_debits_the_source_and_the_event_credits_the_target(transfers):
    _transfer(transfers, 30.0)

    repo = transfers.domain.repository_for(transfers.Account)
    assert repo.get("a").balance == 70.0
    assert repo.get("b").balance == 40.0


def test_transfer_with_insufficient_funds_changes_neither_account(transfers):
    with pytest.raises(ValidationError) as exc:
        _transfer(transfers, 150.0)

    assert exc.value.messages == {"balance": ["Insufficient funds for transfer"]}
    repo = transfers.domain.repository_for(transfers.Account)
    assert repo.get("a").balance == 100.0
    assert repo.get("b").balance == 10.0


def test_debit_raises_money_debited_with_the_transfer_details():
    example = load_example("patterns/one-aggregate-per-transaction/002.py")
    domain = _start(example)
    with domain.domain_context():
        account = example.Account(account_id="a", balance=50.0)
        account.debit(20.0, transfer_id="t7", target_account_id="b")

        assert account.balance == 30.0
        [event] = account._events
        assert isinstance(event, example.MoneyDebited)
        assert event.account_id == "a"
        assert event.amount == 20.0
        assert event.transfer_id == "t7"
        assert event.target_account_id == "b"


def test_the_debit_transaction_alone_leaves_the_target_unchanged():
    example = load_example("patterns/one-aggregate-per-transaction/002.py")
    domain = _start(example, event_processing="async")
    with domain.domain_context():
        repo = domain.repository_for(example.Account)
        repo.add(example.Account(account_id="a", balance=100.0))
        repo.add(example.Account(account_id="b", balance=10.0))

        _transfer(example, 30.0)

        # The first transaction changed only the source account
        assert repo.get("a").balance == 70.0
        assert repo.get("b").balance == 10.0

        # Handing the stored MoneyDebited to the event handler credits the target
        stream = f"{example.Account.meta_.stream_category}-a"
        [message] = [
            m
            for m in domain.event_store.store.read(stream)
            if m.metadata.headers.type.endswith(".MoneyDebited.v1")
        ]
        assert message.data["target_account_id"] == "b"
        assert message.data["amount"] == 30.0

        example.AccountEventHandler._handle(message)

        assert repo.get("a").balance == 70.0
        assert repo.get("b").balance == 40.0


# Order Fulfillment Pipeline


def test_one_order_feeds_three_downstream_aggregates():
    example = load_example("patterns/one-aggregate-per-transaction/003.py")
    domain = _start(example)
    with domain.domain_context():
        domain.repository_for(example.Inventory).add(
            example.Inventory(product_id="p1", available=10)
        )
        domain.repository_for(example.CustomerLoyalty).add(
            example.CustomerLoyalty(customer_id="c1", points=5)
        )

        domain.process(
            example.PlaceOrder(
                order_id="o1",
                customer_id="c1",
                items=[{"product_id": "p1", "quantity": 4, "price": 10.5}],
            )
        )

        assert domain.repository_for(example.Order).get("o1").status == "placed"
        inventory = domain.repository_for(example.Inventory).get("p1")
        assert (inventory.available, inventory.reserved) == (6, 4)
        assert domain.repository_for(example.CustomerLoyalty).get("c1").points == 47
        notification = domain.repository_for(example.Notification).get(
            "confirmation-o1"
        )
        assert notification.recipient_id == "c1"
        assert notification.template == "order_confirmation"
        assert notification.data == {"order_id": "o1", "total": 42.0}


def test_without_event_processing_the_pipeline_changes_only_the_order():
    example = load_example("patterns/one-aggregate-per-transaction/003.py")
    domain = _start(example, event_processing="async")
    with domain.domain_context():
        domain.repository_for(example.Inventory).add(
            example.Inventory(product_id="p1", available=10)
        )
        domain.repository_for(example.CustomerLoyalty).add(
            example.CustomerLoyalty(customer_id="c1", points=5)
        )

        domain.process(
            example.PlaceOrder(
                order_id="o1",
                customer_id="c1",
                items=[{"product_id": "p1", "quantity": 4, "price": 10.5}],
            )
        )

        assert domain.repository_for(example.Order).get("o1").status == "placed"
        assert domain.repository_for(example.Inventory).get("p1").reserved == 0
        assert domain.repository_for(example.CustomerLoyalty).get("c1").points == 5
        assert domain.repository_for(example.Notification).query.all().items == []


# Domain Services: The Exception That Isn't


@pytest.fixture
def eligibility():
    example = load_example("patterns/one-aggregate-per-transaction/004.py")
    domain = _start(example)
    with domain.domain_context():
        domain.repository_for(example.CreditPolicy).add(
            example.CreditPolicy(policy_id="cp", max_transfer_amount=500.0)
        )
        yield example


def _account(example, **overrides):
    values = {
        "account_id": "a",
        "balance": 100.0,
        "overdraft_limit": 50.0,
        "credit_policy_id": "cp",
    }
    values.update(overrides)
    example.domain.repository_for(example.Account).add(example.Account(**values))


def _eligibility_transfer(example, amount):
    example.domain.process(
        example.TransferMoney(
            transfer_id="t1", from_account_id="a", to_account_id="b", amount=amount
        )
    )


def test_an_eligible_transfer_debits_only_the_source(eligibility):
    _account(eligibility)

    _eligibility_transfer(eligibility, 120.0)

    assert eligibility.domain.repository_for(eligibility.Account).get("a").balance == (
        -20.0
    )
    policy = eligibility.domain.repository_for(eligibility.CreditPolicy).get("cp")
    assert policy.max_transfer_amount == 500.0


@pytest.mark.parametrize(
    ("overrides", "amount", "messages"),
    [
        ({"is_frozen": True}, 10.0, {"account": ["Source account is frozen"]}),
        (
            {"balance": 10_000.0},
            600.0,
            {"amount": ["Transfer exceeds maximum of 500.0"]},
        ),
        ({}, 151.0, {"balance": ["Insufficient funds"]}),
    ],
)
def test_an_ineligible_transfer_is_rejected_and_changes_nothing(
    eligibility, overrides, amount, messages
):
    _account(eligibility, **overrides)
    balance_before = (
        eligibility.domain.repository_for(eligibility.Account).get("a").balance
    )

    with pytest.raises(ValidationError) as exc:
        _eligibility_transfer(eligibility, amount)

    assert exc.value.messages == messages
    assert (
        eligibility.domain.repository_for(eligibility.Account).get("a").balance
        == balance_before
    )
