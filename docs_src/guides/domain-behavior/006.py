from datetime import datetime, timezone
from enum import Enum

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import (
    DateTime,
    Float,
    HasMany,
    Identifier,
    Integer,
    String,
    ValueObject,
)

domain = Domain(__file__, load_toml=False)


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id = Identifier(required=True)
    confirmed_at = DateTime(required=True)


@domain.aggregate
class Order:
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
            OrderConfirmed(order_id=self.id, confirmed_at=datetime.now(timezone.utc))
        )


@domain.entity(part_of=Order)
class OrderItem:
    product_id = Identifier(required=True)
    quantity = Integer()
    price = Float()


@domain.value_object(part_of="Inventory")
class Warehouse:
    location = String()
    contact = String()


@domain.event(part_of="Inventory")
class StockReserved:
    product_id = Identifier(required=True)
    quantity = Integer(required=True)
    reserved_at = DateTime(required=True)


@domain.aggregate
class Inventory:
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


@domain.domain_service(part_of=[Order, Inventory])
class place_order:
    def __init__(self, order, inventories):
        super().__init__(*(order, inventories))

        self.order = order
        self.inventories = inventories

    def __call__(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            inventory.reserve_stock(item.quantity)

        self.order.confirm()

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
