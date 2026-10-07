from protean import Domain, handle
from protean.exceptions import ValidationError
from protean.fields import Auto, HasMany, Identifier, Integer, List, String
from protean.utils.globals import current_domain

domain = Domain(name="SmallAggregatesTwoAggregateRule")
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    items: List(required=True)  # Each item: product_id, quantity


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    items = HasMany("OrderItem")
    status: String(default="draft")

    def place(self):
        if self.status != "draft":
            raise ValidationError({"status": ["Only draft orders can be placed"]})

        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                items=[
                    {"product_id": item.product_id, "quantity": item.quantity}
                    for item in self.items
                ],
            )
        )


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)


# --8<-- [start:split]
# Pattern: one aggregate per handler, events for the rest
@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)
    items: List(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order_repo = current_domain.repository_for(Order)
        order = Order(
            order_id=command.order_id,
            items=command.items,
        )
        order.place()  # Raises OrderPlaced event
        order_repo.add(order)


@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    available: Integer(default=0)
    reserved: Integer(default=0)

    def reserve(self, quantity):
        self.available -= quantity
        self.reserved += quantity


@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class InventoryEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        inventory_repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = inventory_repo.get(item["product_id"])
            inventory.reserve(item["quantity"])
            inventory_repo.add(inventory)


# --8<-- [end:split]
