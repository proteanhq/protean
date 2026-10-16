from datetime import UTC, datetime
from enum import Enum

from protean import Domain, current_domain, handle, invariant
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
)

domain = Domain()
domain.config["command_processing"] = "sync"


class OrderStatus(Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status: String(choices=OrderStatus, default=OrderStatus.PENDING.value)
    payment_id: Identifier()

    def quantities_by_product(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for item in self.items:
            totals[item.product_id] = totals.get(item.product_id, 0) + item.quantity
        return totals

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


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer()
    price: Float()


@domain.event(part_of=Order)
class OrderConfirmed:
    order_id: Identifier(required=True)
    items = List(content_type=Dict)
    confirmed_at: DateTime(required=True)


@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    quantity: Integer()


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
        for product_id, quantity in self.order.quantities_by_product().items():
            inventory = next(
                (i for i in self.inventories if i.product_id == product_id), None
            )
            if inventory is None or inventory.quantity < quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(required=True)


# --8<-- [start:handler]
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        order_repo = current_domain.repository_for(Order)
        inventory_repo = current_domain.repository_for(Inventory)

        # Load aggregates
        order = order_repo.get(command.order_id)
        inventories = [inventory_repo.get(item.product_id) for item in order.items]

        # Invoke the domain service. The invariants run here
        service = place_order(order, inventories)
        service()

        # Persist only the primary aggregate
        order_repo.add(order)


# --8<-- [end:handler]
