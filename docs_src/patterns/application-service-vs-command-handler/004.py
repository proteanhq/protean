from protean import Domain
from protean.fields import Auto

domain = Domain(name="EventHandlerReservesStock")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)

    def place(self, product_id: str, quantity: int) -> None:
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                product_id=product_id,
                quantity=quantity,
            )
        )


# --8<-- [start:inventory]
from protean.core.event import BaseEvent
from protean.fields import Identifier, Integer


@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    available: Integer(default=0)
    reserved: Integer(default=0)

    def reserve(self, quantity: int) -> None:
        self.available -= quantity
        self.reserved += quantity


# --8<-- [end:inventory]


# --8<-- [start:event_handler]
from protean import current_domain, handle
from protean.core.event_handler import BaseEventHandler


@domain.event_handler(part_of=Order)
class InventoryEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(event.product_id)
        inventory.reserve(event.quantity)
        repo.add(inventory)


# --8<-- [end:event_handler]

domain.init(traverse=False)
