"""
Event Consumption flows:
1. Event Handler on same Aggregate
2. Event Handler on different Aggregate
3. Event Handler on different Domain
"""

import asyncio
from datetime import datetime, timezone

import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.entity import _LegacyBaseEntity as BaseEntity
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import _LegacyBaseProjection as BaseProjection
from protean.core.value_object import _LegacyBaseValueObject as BaseValueObject
from protean.domain import Domain
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
from protean.server import Engine
from protean.utils import Processing
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


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


class DailyOrders(BaseProjection):
    date = Date(identifier=True)
    total = Integer(required=True)


class OrdersEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def order_placed(self, event: OrderPlaced):
        try:
            projection = current_domain.repository_for(DailyOrders).get(
                event.ordered_at.date()
            )
        except ObjectNotFoundError:
            projection = DailyOrders(date=event.ordered_at.date(), total=1)
            current_domain.repository_for(DailyOrders).add(projection)


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
    test_domain = Domain(name="Test")

    test_domain.config["event_store"] = {
        "provider": "message_db",
        "database_uri": "postgresql://message_store@localhost:5433/message_store",
    }
    test_domain.config["command_processing"] = Processing.ASYNC.value
    test_domain.config["event_processing"] = Processing.ASYNC.value

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
    shipment_domain = Domain(name="Shipment")

    shipment_domain.config["event_store"] = {
        "provider": "message_db",
        "database_uri": "postgresql://message_store@localhost:5433/message_store",
    }
    shipment_domain.config["command_processing"] = Processing.ASYNC.value
    shipment_domain.config["event_processing"] = Processing.ASYNC.value

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
    # Create and set a new loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

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

        # Event Handler on same aggregate updates projection.
        projection = test_domain.repository_for(DailyOrders).get(
            command.ordered_at.date()
        )
        assert projection.total == 1
        assert projection.date == command.ordered_at.date()

        # Event Handler on different aggregate updates history.
        refreshed_customer = test_domain.repository_for(Customer).get(customer.id)
        assert len(refreshed_customer.order_history) == 1

    # Close the loop after the test, before the next domain test
    if not loop.is_closed():
        loop.close()
    asyncio.set_event_loop(None)  # Explicitly unset the loop

    # Create and set a new loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Event Handler on different domain creates a new aggregate.
    # Simulate Engine running in another domain
    with shipment_domain.domain_context():
        engine = Engine(domain=shipment_domain, test_mode=True)
        engine.run()

        # Check effects

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

    # Close the loop after the test
    if not loop.is_closed():
        loop.close()
    asyncio.set_event_loop(None)  # Explicitly unset the loop
