# --8<-- [start:full]
from datetime import UTC, datetime
from enum import Enum

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import (
    DateTime,
    Dict,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)

domain = Domain()


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status: String(choices=OrderStatus, default=OrderStatus.PENDING.value)
    payment_id: Identifier()

    @invariant.post
    def order_should_contain_items(self):
        if not self.items or len(self.items) == 0:
            raise ValidationError({"_entity": ["Order must contain at least one item"]})

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(
            OrderConfirmed(
                order_id=self.id,
                items=[
                    {"product_id": item.product_id, "quantity": item.quantity}
                    for item in self.items
                ],
                confirmed_at=datetime.now(UTC),
            )
        )


@domain.event(part_of=Order)
class OrderConfirmed:
    order_id: Identifier(required=True)
    items = List(content_type=Dict)
    confirmed_at: DateTime(required=True)


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer()
    price: Float()


@domain.value_object(part_of="Inventory")
class Warehouse:
    location: String()
    contact: String()


@domain.event(part_of="Inventory")
class StockReserved:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    reserved_at: DateTime(required=True)


@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    quantity: Integer()
    warehouse = ValueObject(Warehouse)

    def reserve_stock(self, quantity: int):
        self.quantity -= quantity
        self.raise_(
            StockReserved(
                product_id=self.product_id,
                quantity=quantity,
                reserved_at=datetime.now(UTC),
            )
        )


@domain.domain_service(part_of=[Order, Inventory])
class place_order:
    def __init__(self, order, inventories):
        super().__init__(order, inventories)

        self.order = order
        self.inventories = inventories

    def __call__(self):
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
    def order_should_be_confirmed(self):
        if self.order.status != OrderStatus.CONFIRMED.value:
            raise ValidationError({"_service": ["Order was not confirmed"]})

    @invariant.post
    def confirmation_should_list_every_ordered_item(self):
        confirmations = [e for e in self.order._events if isinstance(e, OrderConfirmed)]
        ordered = {item.product_id: item.quantity for item in self.order.items}
        listed = {}
        if confirmations:
            listed = {i["product_id"]: i["quantity"] for i in confirmations[-1].items}

        if listed != ordered:
            raise ValidationError(
                {"_service": ["The confirmation does not list every ordered item"]}
            )


# --8<-- [end:full]
