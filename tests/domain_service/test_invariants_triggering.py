from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

import pytest

from protean import (
    BaseAggregate,
    BaseDomainService,
    BaseEntity,
    BaseEvent,
    BaseValueObject,
    invariant,
)
from protean.exceptions import ValidationError
from protean.fields import (
    DateTime,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class OrderItem(BaseEntity):
    product_id = Identifier(required=True)
    quantity = Integer()
    price = Float()


class OrderItemVO(BaseValueObject):
    product_id = Identifier(required=True)
    quantity = Integer()
    price = Float()


class OrderConfirmed(BaseEvent):
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemVO), required=True)
    confirmed_at = DateTime(required=True)


class Order(BaseAggregate):
    customer_id = Identifier(required=True)
    items = HasMany("OrderItem")
    status = String(choices=OrderStatus, default=OrderStatus.PENDING.value)
    payment_id = Identifier()

    @invariant.post
    def order_should_contain_items(self):
        if not self.items or len(self.items) == 0:
            raise ValidationError({"_entity": ["Order must contain at least one item"]})

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(
            OrderConfirmed(
                customer_id=self.customer_id,
                order_id=self.id,
                confirmed_at=datetime.now(timezone.utc),
                items=[
                    OrderItemVO(
                        product_id=item.product_id,
                        quantity=item.quantity,
                        price=item.price,
                    )
                    for item in self.items
                ],
            )
        )


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

    @invariant.pre
    def order_payment_method_should_be_valid(self):
        if not self.order.payment_id:
            raise ValidationError(
                {"_service": ["Order must have a valid payment method"]}
            )

    @invariant.post
    def total_reserved_value_should_match_order_value(self):
        order_total = sum(item.quantity * item.price for item in self.order.items)
        reserved_total = 0
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            if inventory:
                reserved_total += inventory._events[0].quantity * item.price

        if order_total != reserved_total:
            raise ValidationError(
                {"_service": ["Total reserved value does not match order value"]}
            )

    @invariant.post
    def total_quantity_reserved_should_match_order_quantity(self):
        order_quantity = sum(item.quantity for item in self.order.items)
        reserved_quantity = sum(
            inventory._events[0].quantity
            for inventory in self.inventories
            if inventory._events
        )

        if order_quantity != reserved_quantity:
            raise ValidationError(
                {"_service": ["Total reserved quantity does not match order quantity"]}
            )

    def __call__(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            inventory.reserve_stock(item.quantity)

        self.order.confirm()


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


def test_order_placement_with_sufficient_inventory():
    order = Order(
        customer_id=str(uuid4()),
        payment_id=str(uuid4()),
        items=[OrderItem(product_id=str(uuid4()), quantity=10, price=100)],
    )

    inventory = Inventory(
        product_id=order.items[0].product_id,
        quantity=100,
        warehouse=Warehouse(location="NYC", contact="John Doe"),
    )

    OrderPlacementService(order, [inventory])()

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
        OrderPlacementService(order, [inventory])()

    assert str(exc_info.value) == "{'_service': ['Product is out of stock']}"


def test_order_placement_with_exact_inventory_match():
    order = Order(
        customer_id=str(uuid4()),
        payment_id=str(uuid4()),
        items=[OrderItem(product_id=str(uuid4()), quantity=10, price=100)],
    )

    inventory = Inventory(
        product_id=order.items[0].product_id,
        quantity=10,
        warehouse=Warehouse(location="NYC", contact="John Doe"),
    )

    OrderPlacementService(order, [inventory])()

    assert order.status == OrderStatus.CONFIRMED.value
    assert inventory.quantity == 0
    assert len(order._events) == 1
    assert isinstance(order._events[0], OrderConfirmed)
    assert len(inventory._events) == 1
    assert isinstance(inventory._events[0], StockReserved)
    assert inventory._events[0].quantity == 10
    assert inventory._events[0].product_id == order.items[0].product_id
    assert inventory._events[0].reserved_at is not None


def test_order_placement_with_multiple_items():
    order = Order(
        customer_id=str(uuid4()),
        payment_id=str(uuid4()),
        items=[
            OrderItem(product_id=str(uuid4()), quantity=5, price=100),
            OrderItem(product_id=str(uuid4()), quantity=3, price=200),
        ],
    )

    inventory1 = Inventory(
        product_id=order.items[0].product_id,
        quantity=10,
        warehouse=Warehouse(location="NYC", contact="John Doe"),
    )
    inventory2 = Inventory(
        product_id=order.items[1].product_id,
        quantity=5,
        warehouse=Warehouse(location="NYC", contact="Jane Doe"),
    )

    OrderPlacementService(order, [inventory1, inventory2])()

    assert order.status == OrderStatus.CONFIRMED.value
    assert inventory1.quantity == 5
    assert inventory2.quantity == 2
    assert len(order._events) == 1
    assert isinstance(order._events[0], OrderConfirmed)
    assert len(inventory1._events) == 1
    assert isinstance(inventory1._events[0], StockReserved)
    assert inventory1._events[0].quantity == 5
    assert inventory1._events[0].product_id == order.items[0].product_id
    assert len(inventory2._events) == 1
    assert isinstance(inventory2._events[0], StockReserved)
    assert inventory2._events[0].quantity == 3
    assert inventory2._events[0].product_id == order.items[1].product_id


def test_total_reserved_value_matches_order_value():
    order = Order(
        customer_id=str(uuid4()),
        payment_id=str(uuid4()),
        items=[
            OrderItem(product_id=str(uuid4()), quantity=5, price=100),
            OrderItem(product_id=str(uuid4()), quantity=3, price=200),
        ],
    )

    inventory1 = Inventory(
        product_id=order.items[0].product_id,
        quantity=10,
        warehouse=Warehouse(location="NYC", contact="John Doe"),
    )
    inventory2 = Inventory(
        product_id=order.items[1].product_id,
        quantity=5,
        warehouse=Warehouse(location="NYC", contact="Jane Doe"),
    )

    OrderPlacementService(order, [inventory1, inventory2])()

    assert order.status == OrderStatus.CONFIRMED.value
    assert inventory1.quantity == 5
    assert inventory2.quantity == 2
    assert sum(item.quantity * item.price for item in order.items) == sum(
        item.quantity * item.price for item in order.items
    )


def test_order_placement_with_mismatched_reserved_value():
    order = Order(
        customer_id=str(uuid4()),
        payment_id=str(uuid4()),
        items=[
            OrderItem(product_id=str(uuid4()), quantity=5, price=100),
            OrderItem(product_id=str(uuid4()), quantity=3, price=200),
        ],
    )

    # Inventory quantities are sufficient, but we will manually create a mismatch
    inventory1 = Inventory(
        product_id=order.items[0].product_id,
        quantity=10,
        warehouse=Warehouse(location="NYC", contact="John Doe"),
    )
    inventory2 = Inventory(
        product_id=order.items[1].product_id,
        quantity=5,
        warehouse=Warehouse(location="NYC", contact="Jane Doe"),
    )

    # Manually tampering the inventory to create a mismatch in reserved value
    inventory1.reserve_stock(5)
    inventory2.reserve_stock(1)  # This should be 3 to match order

    with pytest.raises(ValidationError) as exc_info:
        OrderPlacementService(order, [inventory1, inventory2])()

    assert str(exc_info.value) == (
        "{'_service': ['Total reserved quantity does not match order quantity', "
        "'Total reserved value does not match order value']}"
    )


def test_order_placement_with_multiple_pre_condition_errors():
    order = Order(
        customer_id=str(uuid4()),
        payment_id=None,  # Invalid payment method
        items=[OrderItem(product_id=str(uuid4()), quantity=10, price=100)],
    )

    inventory = Inventory(
        product_id=order.items[0].product_id,
        quantity=5,  # Insufficient stock
        warehouse=Warehouse(location="NYC", contact="John Doe"),
    )

    with pytest.raises(ValidationError) as exc_info:
        OrderPlacementService(order, [inventory])()

    assert "Product is out of stock" in str(exc_info.value)
    assert "Order must have a valid payment method" in str(exc_info.value)


def test_order_placement_with_multiple_post_condition_errors():
    order = Order(
        customer_id=str(uuid4()),
        payment_id=str(uuid4()),
        items=[
            OrderItem(product_id=str(uuid4()), quantity=5, price=100),
            OrderItem(product_id=str(uuid4()), quantity=3, price=200),
        ],
    )

    inventory1 = Inventory(
        product_id=order.items[0].product_id,
        quantity=10,
        warehouse=Warehouse(location="NYC", contact="John Doe"),
    )
    inventory2 = Inventory(
        product_id=order.items[1].product_id,
        quantity=5,
        warehouse=Warehouse(location="NYC", contact="Jane Doe"),
    )

    # Manually tampering the inventory to create mismatches in reserved value and quantity
    inventory1.reserve_stock(5)
    inventory2.reserve_stock(1)  # This should be 3 to match order

    with pytest.raises(ValidationError) as exc_info:
        OrderPlacementService(order, [inventory1, inventory2])()

    assert "Total reserved value does not match order value" in str(exc_info.value)
    assert "Total reserved quantity does not match order quantity" in str(
        exc_info.value
    )
