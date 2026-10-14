from protean import Domain, current_domain, handle
from protean.fields import Identifier, Integer, List, String

domain = Domain(name="ecommerce")


# --8<-- [start:model]
@domain.aggregate
class Order:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

    def ship(self):
        self.raise_(
            OrderShipped(
                order_id=self.id,
                product_id=self.product_id,
                quantity=self.quantity,
            )
        )


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    in_stock: Integer(required=True)
    applied_order_ids: List(content_type=String)

    def reduce_stock(self, order_id, quantity):
        self.in_stock -= quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]


@domain.command(part_of=Inventory)
class ReduceStock:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


# --8<-- [end:model]


# --8<-- [start:hand_off]
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    """Asks Inventory to reduce stock when an order ships."""

    @handle(OrderShipped)
    def reduce_stock(self, event):
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)

        # Events arrive at least once. Skip an order already applied.
        if command.order_id in inventory.applied_order_ids:
            return

        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)


# --8<-- [end:hand_off]
