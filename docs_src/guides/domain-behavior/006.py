from datetime import datetime, timezone
from enum import Enum

from protean import Domain
from protean.fields import (
    DateTime,
    Float,
    Identifier,
    Integer,
    HasMany,
    String,
)

domain = Domain(__file__)


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


@domain.event
class OrderConfirmed:
    order_id = Identifier(required=True)
    confirmed_at = DateTime(required=True)

    class Meta:
        part_of = "Order"


@domain.aggregate
class Order:
    customer_id = Identifier(required=True)
    items = HasMany("OrderItem")
    status = String(choices=OrderStatus, default=OrderStatus.PENDING.value)
    payment_id = Identifier()

    def confirm(self):
        self.status = OrderStatus.CONFIRMED.value
        self.raise_(
            OrderConfirmed(order_id=self.id, confirmed_at=datetime.now(timezone.utc))
        )


@domain.entity
class OrderItem:
    product_id = Identifier(required=True)
    quantity = Integer()
    price = Float()

    class Meta:
        part_of = Order


@domain.event
class StockReserved:
    product_id = Identifier(required=True)
    quantity = Integer(required=True)
    reserved_at = DateTime(required=True)

    class Meta:
        part_of = "Inventory"


@domain.aggregate
class Inventory:
    product_id = Identifier(required=True)
    quantity = Integer()

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
class OrderPlacementService:
    @classmethod
    def place_order(
        cls, order: Order, inventories: list[Inventory]
    ) -> tuple[Order, list[Inventory]]:
        for item in order.items:
            inventory = next(
                (i for i in inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise Exception("Product is out of stock")

            inventory.reserve_stock(item.quantity)

        order.confirm()

        return order, inventories
