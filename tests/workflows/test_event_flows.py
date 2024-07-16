"""
Event Consumption flows:
1. Event Handler on same Aggregate
2. Event Handler on different Aggregate
3. Event Handler on different Domain
"""

import asyncio
from datetime import datetime, timezone

import pytest

from protean import (
    BaseAggregate,
    BaseCommand,
    BaseCommandHandler,
    BaseEntity,
    BaseEvent,
    BaseEventHandler,
    BaseValueObject,
    BaseView,
    Domain,
    handle,
)
from protean.exceptions import ObjectNotFoundError
from protean.fields import (
    Date,
    DateTime,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)
from protean.globals import current_domain
from protean.server import Engine
from protean.utils import CommandProcessing, EventProcessing


class Order(BaseAggregate):
    customer_id = Identifier(required=True)
    items = HasMany("OrderItem")
    total = Float(required=True)
    ordered_at = DateTime(default=lambda: datetime.now(timezone.utc))


class OrderItem(BaseEntity):
    product_id = Identifier(required=True)
    price = Float(required=True)
    quantity = Integer(required=True)


# FIXME Auto-generate ValueObject from Entity?
class OrderItemValueObject(BaseValueObject):
    product_id = Identifier(required=True)
    price = Float(required=True)
    quantity = Integer(required=True)


class PlaceOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    customer_id = Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemValueObject))
    total = Float(required=True)
    ordered_at = DateTime(required=True)


class OrderPlaced(BaseEvent):
    order_id = Identifier(identifier=True)
    customer_id = Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemValueObject))
    total = Float(required=True)
    ordered_at = DateTime(required=True)


class OrdersCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # FIXME Cumbersome conversion to and from OrderItemValueObject
        items = [OrderItem(**item.to_dict()) for item in command.items]
        order = Order(
            id=command.order_id,
            customer_id=command.customer_id,
            items=items,
            total=command.total,
            ordered_at=command.ordered_at,
        )
        order.raise_(
            OrderPlaced(
                order_id=order.id,
                customer_id=order.customer_id,
                items=command.items,
                total=order.total,
                ordered_at=order.ordered_at,
            )
        )
        current_domain.repository_for(Order).add(order)


class DailyOrders(BaseView):
    date = Date(identifier=True)
    total = Integer(required=True)


class OrdersEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def order_placed(self, event: OrderPlaced):
        try:
            view = current_domain.repository_for(DailyOrders).get(
                event.ordered_at.date()
            )
        except ObjectNotFoundError:
            view = DailyOrders(date=event.ordered_at.date(), total=1)
            current_domain.repository_for(DailyOrders).add(view)


class Customer(BaseAggregate):
    name = String(required=True)
    order_history = HasMany("OrderHistory")


class OrderHistory(BaseEntity):
    order_id = Identifier(identifier=True)
    items = List(content_type=ValueObject(OrderItemValueObject))
    total = Float(required=True)
    ordered_at = DateTime(required=True)


class CustomerOrderEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def order_placed(self, event: OrderPlaced):
        customer = current_domain.repository_for(Customer).get(event.customer_id)
        order_history = OrderHistory(
            order_id=event.order_id,
            items=event.items,
            total=event.total,
            ordered_at=event.ordered_at,
        )
        customer.add_order_history(order_history)
        current_domain.repository_for(Customer).add(customer)


class Shipment(BaseAggregate):
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemValueObject))
    status = String(
        choices=["PENDING", "SHIPPED", "DELIVERED", "CANCELLED"], default="PENDING"
    )
    shipped_at = DateTime()


class ShipmentEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def order_placed(self, event: OrderPlaced):
        shipment = Shipment(
            order_id=event.order_id,
            customer_id=event.customer_id,
            items=event.items,
        )
        current_domain.repository_for(Shipment).add(shipment)


@pytest.fixture
def test_domain():
    test_domain = Domain(__file__, "Test")

    test_domain.config["event_store"] = {
        "provider": "message_db",
        "database_uri": "postgresql://message_store@localhost:5433/message_store",
    }
    test_domain.config["command_processing"] = CommandProcessing.ASYNC.value
    test_domain.config["event_processing"] = EventProcessing.ASYNC.value

    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(OrdersCommandHandler, part_of=Order)
    test_domain.register(OrdersEventHandler, part_of=Order)
    test_domain.register(DailyOrders)

    test_domain.register(Customer)
    test_domain.register(OrderHistory, part_of=Customer)
    test_domain.register(
        CustomerOrderEventHandler, part_of=Customer, stream_category="test::order"
    )
    test_domain.init(traverse=False)

    yield test_domain


@pytest.fixture
def shipment_domain():
    shipment_domain = Domain(__file__, "Shipment")

    shipment_domain.config["event_store"] = {
        "provider": "message_db",
        "database_uri": "postgresql://message_store@localhost:5433/message_store",
    }
    shipment_domain.config["command_processing"] = CommandProcessing.ASYNC.value
    shipment_domain.config["event_processing"] = EventProcessing.ASYNC.value

    shipment_domain.register(Shipment)
    shipment_domain.register(
        ShipmentEventHandler, part_of=Shipment, stream_category="test::order"
    )

    # Set up external event in the shipment domain
    #   This is the case when both domains in play are built in Protean
    shipment_domain.register_external_event(OrderPlaced, "Test.OrderPlaced.v1")

    shipment_domain.init(traverse=False)

    yield shipment_domain


@pytest.mark.message_db
def test_workflow_among_protean_domains(test_domain, shipment_domain):
    with test_domain.domain_context():
        customer = Customer(id="1", name="John Doe")
        test_domain.repository_for(Customer).add(customer)

        # Initiate command
        command = PlaceOrder(
            order_id="1",
            customer_id="1",
            items=[OrderItemValueObject(product_id="1", price=100.0, quantity=1)],
            total=100.0,
            ordered_at=datetime.now(timezone.utc),
        )
        test_domain.process(command)

        # Start server and process command
        engine = Engine(domain=test_domain, test_mode=True)
        engine.run()

        # Check effects

        # Event Handler on same aggregate updates view.
        view = test_domain.repository_for(DailyOrders).get(command.ordered_at.date())
        assert view.total == 1
        assert view.date == command.ordered_at.date()

        # Event Handler on different aggregate updates history.
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)
        assert len(refreshed_customer.order_history) == 1

    # Event Handler on different domain creates a new aggregate.
    # Simulate Engine running in another domain
    with shipment_domain.domain_context():
        # Create a new event loop
        new_loop = asyncio.new_event_loop()

        # Set the new event loop as the current event loop
        asyncio.set_event_loop(new_loop)

        engine = Engine(domain=shipment_domain, test_mode=True)
        engine.run()

        shipments = (
            shipment_domain.repository_for(Shipment)
            ._dao.query.filter(order_id=command.order_id)
            .all()
            .items
        )
        assert len(shipments) == 1
        assert shipments[0].order_id == command.order_id
        assert shipments[0].customer_id == command.customer_id
        assert shipments[0].items == command.items
        assert shipments[0].status == "PENDING"
        assert shipments[0].shipped_at is None
