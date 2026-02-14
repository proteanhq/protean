from datetime import datetime, timezone
from enum import Enum

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import HasMany, ValueObject

domain = Domain()


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: str
    confirmed_at: datetime


@domain.aggregate
class Order:
    customer_id: str
    items = HasMany("OrderItem")
    status: OrderStatus = OrderStatus.PENDING.value
    payment_id: str | None = None

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
    product_id: str
    quantity: int | None = None
    price: float | None = None


@domain.value_object(part_of="Inventory")
class Warehouse:
    location: str | None = None
    contact: str | None = None


@domain.event(part_of="Inventory")
class StockReserved:
    product_id: str
    quantity: int
    reserved_at: datetime


@domain.aggregate
class Inventory:
    product_id: str
    quantity: int | None = None
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
class OrderPlacementService:
    @classmethod
    def place_order(cls, order, inventories):
        for item in order.items:
            inventory = next(
                (i for i in inventories if i.product_id == item.product_id), None
            )
            inventory.reserve_stock(item.quantity)

        order.confirm()
