"""The examples on the event handlers guide behave as the page says."""

import logging

import pytest

from protean.exceptions import IncorrectUsageError, SendError
from protean.server.subscription import ConfigResolver
from protean.server.subscription.profiles import SubscriptionType
from protean.utils.eventing import Message
from protean.utils.mixins import _get_transient_retry_config
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def bookstore():
    example = load_example("guides/consume-state/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def bookshop():
    example = load_example("guides/consume-state/event-handlers/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def orders():
    example = load_example("guides/consume-state/event-handlers/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def shipping():
    example = load_example("guides/consume-state/event-handlers/003.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _ship_one_order(example):
    order = example.Order(book_id="book-1", quantity=10, total_amount=100)
    example.domain.repository_for(example.Order).add(order)
    inventory = example.Inventory(book_id="book-1", in_stock=100)
    example.domain.repository_for(example.Inventory).add(inventory)

    order.ship_order()
    example.domain.repository_for(example.Order).add(order)
    return order, inventory


# --- Defining an event handler ---------------------------------------------


def test_shipping_an_order_reduces_the_stock_by_its_quantity(bookstore):
    order, inventory = _ship_one_order(bookstore)

    stock = bookstore.domain.repository_for(bookstore.Inventory).get(inventory.id)
    assert stock.to_dict() == {
        "book_id": "book-1",
        "in_stock": 90,
        "applied_order_ids": [order.id],
        "id": inventory.id,
        "_version": 1,
    }
    assert order.status == "SHIPPED"


def test_a_repeated_reduce_stock_for_the_same_order_changes_nothing(bookstore):
    order, inventory = _ship_one_order(bookstore)

    bookstore.domain.process(
        bookstore.ReduceStock(order_id=order.id, book_id="book-1", quantity=10)
    )

    stock = bookstore.domain.repository_for(bookstore.Inventory).get(inventory.id)
    assert stock.in_stock == 90
    assert stock.applied_order_ids == [order.id]


# --- The @handle decorator --------------------------------------------------


def test_one_handler_class_reacts_to_both_shipping_and_cancelling(bookshop):
    order_repo = bookshop.domain.repository_for(bookshop.Order)
    inventory_repo = bookshop.domain.repository_for(bookshop.Inventory)
    inventory = bookshop.Inventory(book_id="book-1", in_stock=100)
    inventory_repo.add(inventory)
    order = bookshop.Order(book_id="book-1", quantity=10)

    order.ship()
    order_repo.add(order)
    assert inventory_repo.get(inventory.id).in_stock == 90

    order.cancel()
    order_repo.add(order)
    assert inventory_repo.get(inventory.id).in_stock == 100


def test_the_any_handler_records_every_order_event(orders):
    order = orders.Order(quantity=3)
    order.place()
    order.ship()
    orders.domain.repository_for(orders.Order).add(order)

    entries = orders.domain.repository_for(orders.AuditEntry).query.all().items
    assert sorted(
        (entry.event_type, entry.payload["order_id"]) for entry in entries
    ) == [("OrderPlaced", order.id), ("OrderShipped", order.id)]
    placed = next(entry for entry in entries if entry.event_type == "OrderPlaced")
    assert placed.payload["quantity"] == 3


# --- Configuration options --------------------------------------------------


def test_source_stream_becomes_the_subscription_origin_stream_filter(orders):
    config = ConfigResolver(orders.domain).resolve(orders.EmailNotifications)

    assert orders.EmailNotifications.meta_.source_stream == "manage_order"
    assert config.origin_stream == "manage_order"


def test_a_handler_without_part_of_or_stream_category_fails_to_register(orders):
    with pytest.raises(IncorrectUsageError):

        @orders.domain.event_handler
        class Unattached:
            pass


def test_the_production_profile_handler_uses_its_own_tick_and_dlq(orders):
    config = ConfigResolver(orders.domain).resolve(orders.OrderEventHandler)

    assert config.subscription_type == SubscriptionType.STREAM
    assert config.messages_per_tick == 100
    assert config.enable_dlq is True


def test_the_critical_handler_retries_five_times_before_the_dlq(orders):
    config = ConfigResolver(orders.domain).resolve(orders.CriticalOrderHandler)

    assert config.subscription_type == SubscriptionType.STREAM
    assert config.max_retries == 5
    assert config.enable_dlq is True


def test_the_inventory_sync_handler_retries_transient_failures_three_times(orders):
    policy = _get_transient_retry_config(orders.InventorySync)

    assert policy["max_retries"] == 3
    assert policy["backoff"] == "exponential"
    assert policy["exceptions"] == (ConnectionError, TimeoutError, SendError)


def test_a_handler_without_retries_does_not_retry_transient_failures(orders):
    assert _get_transient_retry_config(orders.CriticalOrderHandler)["max_retries"] == 0


# --- Error handling ---------------------------------------------------------


def test_handle_error_logs_the_failed_event_type_and_the_error(shipping, caplog):
    order = shipping.Order()
    order.ship()
    message = Message.from_domain_object(order._events[0])

    with caplog.at_level(logging.ERROR, logger=shipping.logger.name):
        shipping.OrderEventHandler.handle_error(
            ConnectionError("warehouse offline"), message
        )

    assert (
        "Failed to process event Shipping.OrderShipped.v1: warehouse offline"
        in caplog.text
    )
