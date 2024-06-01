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
    invariant,
)
from protean.exceptions import ValidationError
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

    class Meta:
        part_of = "Order"


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

    class Meta:
        part_of = Order


class Warehouse(BaseValueObject):
    location = String()
    contact = String()

    class Meta:
        part_of = "Inventory"


class StockReserved(BaseEvent):
    product_id = Identifier(required=True)
    quantity = Integer(required=True)
    reserved_at = DateTime(required=True)

    class Meta:
        part_of = "Inventory"


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


class OrderPlacementRegularService(BaseDomainService):
    class Meta:
        part_of = [Order, Inventory]

    def __init__(self, order, inventories):
        super().__init__(*(order, inventories))

        self.order = order
        self.inventories = inventories

    @invariant.pre
    def inventory_should_have_sufficient_stock(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    def place_order(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            inventory.reserve_stock(item.quantity)

        self.order.confirm()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderItem)
    test_domain.register(Warehouse)
    test_domain.register(Inventory)
    test_domain.register(OrderConfirmed)
    test_domain.register(StockReserved)
    test_domain.register(OrderPlacementRegularService)
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

        OrderPlacementRegularService(order, [inventory]).place_order()

        assert order.status == OrderStatus.CONFIRMED.value
        assert inventory.quantity == 90
        assert len(order._events) == 1
        assert isinstance(order._events[0], OrderConfirmed)
        assert len(inventory._events) == 1
        assert isinstance(inventory._events[0], StockReserved)
        assert inventory._events[0].quantity == 10
        assert inventory._events[0].product_id == order.items[0].product_id
        assert inventory._events[0].reserved_at is not None


def test_order_placement_with_insufficient_inventory():
    order = Order(
        customer_id=str(uuid4()),
        payment_id=str(uuid4()),
        items=[OrderItem(product_id=str(uuid4()), quantity=10, price=100)],
    )

    inventory = Inventory(
        product_id=order.items[0].product_id,
        quantity=5,
        warehouse=Warehouse(location="NYC", contact="John Doe"),
    )

    with pytest.raises(ValidationError) as exc_info:
        OrderPlacementRegularService(order, [inventory]).place_order()

    assert str(exc_info.value) == "{'_service': ['Product is out of stock']}"
