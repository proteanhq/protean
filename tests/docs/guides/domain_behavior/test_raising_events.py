"""The examples on the raising events guide behave as the page says."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def banking():
    example = load_example("guides/domain-behavior/002.py")
    example.banking.init(traverse=False)
    with example.banking.domain_context():
        yield example


@pytest.fixture
def library():
    example = load_example("guides/domain-behavior/010.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def es_orders():
    example = load_example("guides/domain-behavior/raising-events/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def test_withdraw_collects_the_event_on_the_aggregate(banking):
    account = banking.Account(
        account_number="1234", balance=1000.0, overdraft_limit=50.0
    )

    account.withdraw(500.0)

    assert len(account._events) == 1
    event = account._events[0]
    assert isinstance(event, banking.AccountWithdrawn)
    assert (event.account_number, event.amount) == ("1234", 500.0)


def test_persisting_the_aggregate_writes_the_event_and_clears_the_list(banking):
    account = banking.Account(
        account_number="1234", balance=1000.0, overdraft_limit=50.0
    )
    account.withdraw(500.0)

    banking.banking.repository_for(banking.Account).add(account)

    assert account._events == []
    stored = banking.banking.event_store.store.read(
        f"{banking.Account.meta_.stream_category}-{account.id}"
    )
    assert [message.data["amount"] for message in stored] == [500.0]


def test_an_entity_event_carries_the_owning_aggregate_id(library):
    hold = library.Hold(book_id="book-1")
    patron = library.Patron(name="Jane", holds=[hold])

    patron.cancel_hold(hold.id)

    assert hold.status == "CANCELLED"
    assert len(patron._events) == 1
    event = patron._events[0]
    assert isinstance(event, library.HoldCanceled)
    assert (event.hold_id, event.book_id, event.patron_id) == (
        hold.id,
        "book-1",
        patron.id,
    )


def test_place_and_confirm_change_state_through_apply_handlers(es_orders):
    order = es_orders.Order.place("Jane")

    assert (order.customer_name, order.status) == ("Jane", "PENDING")

    order.confirm()

    assert order.status == "CONFIRMED"
    assert [type(event) for event in order._events] == [
        es_orders.OrderPlaced,
        es_orders.OrderConfirmed,
    ]
    assert order._events[0].order_id == order.id


def test_replaying_the_events_rebuilds_the_same_order(es_orders):
    order = es_orders.Order.place("Jane")
    order.confirm()

    rebuilt = es_orders.Order.from_events(order._events)

    assert (rebuilt.id, rebuilt.customer_name, rebuilt.status) == (
        order.id,
        "Jane",
        "CONFIRMED",
    )
