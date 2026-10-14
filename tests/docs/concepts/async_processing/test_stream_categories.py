"""The examples on ``docs/concepts/async-processing/stream-categories.md`` behave as the page says."""

import pytest

from protean.fields import Identifier
from protean.server import Engine
from protean.utils import fqn
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _init(example):
    example.domain.init(traverse=False)
    return example.domain.domain_context()


def _run_engine(domain):
    engine = Engine(domain, test_mode=True)
    engine.run()
    return engine


def _place_order(example):
    order = example.Order()
    order.raise_(example.OrderPlaced(order_id=order.id))
    example.domain.repository_for(example.Order).add(order)
    return order


def _last_position(domain):
    """Return the event store position of the last stored message."""
    message = domain.event_store.store.read("$all")[-1]
    return message.metadata.event_store.global_position


# Messages are grouped per aggregate under the domain-prefixed category


def test_the_domain_name_prefixes_the_stream_category():
    example = load_example("concepts/async-processing/stream-categories/001.py")
    with _init(example):
        assert example.Order.meta_.stream_category == "ecommerce::order"


def test_the_default_category_is_the_snake_case_class_name():
    example = load_example("concepts/async-processing/stream-categories/001.py")
    with _init(example):
        assert example.User.meta_.stream_category == "ecommerce::user"
        assert example.OrderItem.meta_.stream_category == "ecommerce::order_item"


def test_an_explicit_category_replaces_the_default():
    example = load_example("concepts/async-processing/stream-categories/002.py")
    with _init(example):
        assert example.Order.meta_.stream_category == "ecommerce::customer_orders"


def test_an_event_is_stored_in_its_aggregate_instance_stream():
    example = load_example("concepts/async-processing/stream-categories/003.py")
    with _init(example):
        order = _place_order(example)

        (message,) = example.domain.event_store.store.read("$all")
        assert message.metadata.headers.stream == f"ecommerce::order-{order.id}"


def test_a_command_goes_to_its_aggregate_command_stream():
    example = load_example("concepts/async-processing/stream-categories/001.py")
    example.domain.config["command_processing"] = "async"
    with _init(example):
        example.domain.process(example.PlaceOrder(order_id="123"))

        (message,) = example.domain.event_store.store.read("$all")
        assert message.metadata.headers.stream.startswith("ecommerce::order:command-")


# Handlers subscribe to a stream category


def test_a_handler_takes_its_aggregate_category():
    example = load_example("concepts/async-processing/stream-categories/003.py")
    with _init(example):
        engine = Engine(example.domain, test_mode=True)
        try:
            subscription = engine.subscriptions[fqn(example.OrderEventHandler)]
            assert subscription.stream_category == "ecommerce::order"
        finally:
            engine.loop.close()


def test_the_default_handler_consumes_the_order_event():
    example = load_example("concepts/async-processing/stream-categories/003.py")
    with _init(example):
        _place_order(example)
        placed_at = _last_position(example.domain)
        engine = _run_engine(example.domain)

        handler = engine.subscriptions[fqn(example.OrderEventHandler)]
        report = engine.subscriptions[fqn(example.OrderReportHandler)]
        assert handler.current_position == placed_at
        # The order event is on "order", not on "all_orders".
        assert report.current_position == -1


def test_an_explicit_handler_category_reads_the_shared_stream():
    example = load_example("concepts/async-processing/stream-categories/003.py")

    @example.domain.aggregate(stream_category="all_orders")
    class Return: ...

    @example.domain.event(part_of=Return)
    class ReturnRequested:
        return_id = Identifier(required=True)

    with _init(example):
        assert example.OrderReportHandler.meta_.stream_category == "all_orders"

        returned = Return()
        returned.raise_(ReturnRequested(return_id=returned.id))
        example.domain.repository_for(Return).add(returned)
        requested_at = _last_position(example.domain)
        engine = _run_engine(example.domain)

        report = engine.subscriptions[fqn(example.OrderReportHandler)]
        handler = engine.subscriptions[fqn(example.OrderEventHandler)]
        assert report.current_position == requested_at
        assert handler.current_position == -1


# Changing another aggregate through a command


def _stock(example, product_id="book-1", in_stock=100):
    inventory = example.Inventory(product_id=product_id, in_stock=in_stock)
    example.domain.repository_for(example.Inventory).add(inventory)
    return inventory


def test_the_event_handler_and_command_handler_read_their_own_categories():
    example = load_example("concepts/async-processing/stream-categories/004.py")
    with _init(example):
        assert example.OrderEventHandler.meta_.stream_category == "ecommerce::order"
        assert (
            example.InventoryCommandHandler.meta_.stream_category
            == "ecommerce::inventory:command"
        )
        assert example.ReduceStock.meta_.part_of is example.Inventory


def test_shipping_an_order_reduces_stock_through_the_command():
    example = load_example("concepts/async-processing/stream-categories/004.py")
    with _init(example):
        _stock(example)
        order = example.Order(product_id="book-1", quantity=10)
        order.ship()
        example.domain.repository_for(example.Order).add(order)

        _run_engine(example.domain)

        inventory = example.domain.repository_for(example.Inventory).get("book-1")
        assert inventory.in_stock == 90
        assert inventory.applied_order_ids == [order.id]


def test_a_repeated_command_for_the_same_order_is_skipped():
    example = load_example("concepts/async-processing/stream-categories/004.py")
    with _init(example):
        _stock(example)
        command = example.ReduceStock(
            order_id="order-1", product_id="book-1", quantity=10
        )
        example.domain.process(command, asynchronous=False)
        example.domain.process(command, asynchronous=False)

        inventory = example.domain.repository_for(example.Inventory).get("book-1")
        assert inventory.in_stock == 90


# Several handlers on one stream


def test_each_handler_on_a_stream_gets_its_own_subscription():
    example = load_example("concepts/async-processing/stream-categories/005.py")
    with _init(example):
        _place_order(example)
        placed_at = _last_position(example.domain)
        engine = _run_engine(example.domain)

        notification = engine.subscriptions[fqn(example.OrderNotificationHandler)]
        analytics = engine.subscriptions[fqn(example.OrderAnalyticsHandler)]
        assert notification is not analytics
        assert notification.stream_category == "ecommerce::order"
        assert analytics.stream_category == "ecommerce::order"
        # Each tracks its own position over the same event.
        assert notification.current_position == placed_at
        assert analytics.current_position == placed_at


# Event sourcing and fact events


def test_the_account_is_event_sourced_on_its_own_category():
    example = load_example("concepts/async-processing/stream-categories/006.py")
    with _init(example):
        assert example.Account.meta_.is_event_sourced is True
        assert example.Account.meta_.stream_category == "ecommerce::account"


def test_fact_events_go_to_the_fact_stream():
    example = load_example("concepts/async-processing/stream-categories/006.py")
    with _init(example):
        user = example.User()
        example.domain.repository_for(example.User).add(user)

        streams = [
            message.metadata.headers.stream
            for message in example.domain.event_store.store.read("$all")
        ]
        assert streams == [f"ecommerce::user-fact-{user.id}"]


# Best practices and patterns


def test_the_descriptive_and_the_short_name_are_both_used_as_given():
    example = load_example("concepts/async-processing/stream-categories/007.py")
    with _init(example):
        assert (
            example.DescriptiveOrder.meta_.stream_category
            == "ecommerce::customer_order"
        )
        assert example.LessClearOrder.meta_.stream_category == "ecommerce::ord"


def test_grouped_aggregates_share_a_prefix():
    example = load_example("concepts/async-processing/stream-categories/008.py")
    with _init(example):
        assert example.Order.meta_.stream_category == "ecommerce::order"
        assert example.OrderItem.meta_.stream_category == "ecommerce::order_item"
        assert example.Shipment.meta_.stream_category == "ecommerce::order_shipment"


def test_an_override_replaces_the_derived_default():
    example = load_example("concepts/async-processing/stream-categories/008.py")

    @example.domain.aggregate
    class PurchaseOrderDefault: ...

    with _init(example):
        assert example.PurchaseOrder.meta_.stream_category == "ecommerce::order"
        assert (
            PurchaseOrderDefault.meta_.stream_category
            == "ecommerce::purchase_order_default"
        )


def test_a_single_handler_subscribes_to_its_aggregate():
    example = load_example("concepts/async-processing/stream-categories/009.py")
    with _init(example):
        assert example.OrderEventHandler.meta_.stream_category == "ecommerce::order"


def test_every_handler_of_the_order_reads_the_order_category():
    example = load_example("concepts/async-processing/stream-categories/010.py")
    with _init(example):
        engine = Engine(example.domain, test_mode=True)
        try:
            categories = {
                name.rsplit(".", 1)[-1].split("-", 1)[0]: sub.stream_category
                for name, sub in engine.subscriptions.items()
            }
        finally:
            engine.loop.close()

        assert categories == {
            "OrderNotificationHandler": "ecommerce::order",
            "OrderAnalyticsHandler": "ecommerce::order",
            "OrderSummaryProjector": "ecommerce::order",
        }


def test_the_cross_aggregate_handlers_sit_on_their_own_aggregates():
    example = load_example("concepts/async-processing/stream-categories/011.py")
    with _init(example):
        assert example.OrderEventHandler.meta_.stream_category == "ecommerce::order"
        assert (
            example.InventoryCommandHandler.meta_.stream_category
            == "ecommerce::inventory:command"
        )


def test_the_dashboard_projector_reads_three_categories():
    example = load_example("concepts/async-processing/stream-categories/012.py")
    with _init(example):
        assert example.SalesDashboardProjector.meta_.stream_categories == [
            "ecommerce::order",
            "ecommerce::customer",
            "ecommerce::product",
        ]
