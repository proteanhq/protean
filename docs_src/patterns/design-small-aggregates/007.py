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
# Pattern: one aggregate per handler, an event and a command for the rest
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
    applied_order_ids: List(content_type=String)

    def reserve(self, order_id, quantity):
        self.available -= quantity
        self.reserved += quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]


@domain.command(part_of=Inventory)
class ReserveStock:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # One ReserveStock per product, so the order id alone marks it applied
        quantities = {}
        for item in event.items:
            product_id = item["product_id"]
            quantities[product_id] = quantities.get(product_id, 0) + item["quantity"]

        for product_id, quantity in quantities.items():
            current_domain.process(
                ReserveStock(
                    order_id=event.order_id,
                    product_id=product_id,
                    quantity=quantity,
                )
            )


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReserveStock)
    def reserve_stock(self, command: ReserveStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)
        if command.order_id in inventory.applied_order_ids:
            return  # This order was already applied
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)


# --8<-- [end:split]
