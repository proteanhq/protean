from protean import Domain, current_domain, handle
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.fields import Auto, Identifier, Integer

domain = Domain(name="EventHandlerProcessesCommand")


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


@domain.command(part_of=Inventory)
class ReserveInventory(BaseCommand):
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    order_id: Identifier(required=True)


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler(BaseCommandHandler):
    @handle(ReserveInventory)
    def reserve_inventory(self, command: ReserveInventory):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)
        inventory.reserve(command.quantity)
        repo.add(inventory)


# --8<-- [start:event_handler]
from protean.core.event_handler import BaseEventHandler


@domain.event_handler(part_of=Order)
class InventoryEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        current_domain.process(
            ReserveInventory(
                product_id=event.product_id,
                quantity=event.quantity,
                order_id=event.order_id,
            )
        )


# --8<-- [end:event_handler]

domain.init(traverse=False)
