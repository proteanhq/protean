import pytest

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from protean import (
    BaseAggregate,
    BaseDomainService,
    BaseEvent,
    BaseValueObject,
    BaseEntity,
)
from protean.fields import (
    DateTime,
    Float,
    Identifier,
    Integer,
    HasMany,
    String,
    ValueObject,
)


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class OrderConfirmed(BaseEvent):
    order_id = Identifier(required=True)
    confirmed_at = DateTime(required=True)


class Order(BaseAggregate):
    customer_id = Identifier(required=True)
    items = HasMany("OrderItem")
    status = String(choices=OrderStatus, default=OrderStatus.PENDING.value)
    payment_id = Identifier()

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(
            OrderConfirmed(order_id=self.id, confirmed_at=datetime.now(timezone.utc))
        )


class OrderItem(BaseEntity):
    product_id = Identifier(required=True)
    quantity = Integer()
    price = Float()


class Warehouse(BaseValueObject):
    location = String()
    contact = String()


class StockReserved(BaseEvent):
    product_id = Identifier(required=True)
    quantity = Integer(required=True)
    reserved_at = DateTime(required=True)


class Inventory(BaseAggregate):
    product_id = Identifier(required=True)
    quantity = Integer()
    warehouse = ValueObject(Warehouse)

    def reserve_stock(self, quantity: int):
        self.quantity -= quantity
        self.raise_(
            StockReserved(
                product_id=self.product_id,
                quantity=quantity,
                reserved_at=datetime.now(timezone.utc),
            )
        )


class OrderPlacementService(BaseDomainService):
    @classmethod
    def place_order(cls, order: Order, inventories: list[Inventory]):
        for item in order.items:
            inventory = next(
                (i for i in inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise Exception("Product is out of stock")

            inventory.reserve_stock(item.quantity)

        order.confirm()

        return order, inventories


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.register(OrderConfirmed, part_of=Order)
    test_domain.register(Inventory)
    test_domain.register(Warehouse, part_of=Inventory)
    test_domain.register(StockReserved, part_of=Inventory)
    test_domain.register(OrderPlacementService, part_of=[Order, Inventory])
    test_domain.init(traverse=False)


class TestOrderPlacement:
    def test_order_placement(self):
        order = Order(customer_id=str(uuid4()), payment_id=str(uuid4()))
        order.add_items(OrderItem(product_id=str(uuid4()), quantity=10, price=100))

        inventory = Inventory(
            product_id=order.items[0].product_id,
            quantity=100,
            warehouse=Warehouse(location="NYC", contact="John Doe"),
        )

        order, inventories = OrderPlacementService.place_order(order, [inventory])

        assert order.status == OrderStatus.CONFIRMED.value
        assert inventories[0].quantity == 90
        assert len(order._events) == 1
        assert isinstance(order._events[0], OrderConfirmed)
        assert len(inventory._events) == 1
        assert isinstance(inventory._events[0], StockReserved)
        assert inventory._events[0].quantity == 10
        assert inventory._events[0].product_id == order.items[0].product_id
        assert inventory._events[0].reserved_at is not None
