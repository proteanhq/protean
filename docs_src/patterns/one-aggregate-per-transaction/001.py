from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier, Integer, List, String, ValueObject

domain = Domain(name="OneAggregatePerTransactionOrders")
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:command_handler]
@domain.value_object
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    price: Float(required=True)


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    items: List(content_type=ValueObject(OrderItem))
    total: Float(default=0.0)
    status: String(max_length=20, default="new")

    def place(self):
        self.status = "placed"
        self.total = sum(item.price * item.quantity for item in self.items)
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                items=[item.to_dict() for item in self.items],
                total=self.total,
            )
        )


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # The @handle decorator wraps this method in a UoW
        repo = current_domain.repository_for(Order)
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            items=command.items,
        )
        order.place()  # Mutates and raises OrderPlaced event
        repo.add(order)
        # UoW commits: Order is persisted, OrderPlaced event is published


# --8<-- [end:command_handler]


# --8<-- [start:event]
@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)


# --8<-- [end:event]


# --8<-- [start:event_handler]
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
        # Stays with Order, which owns the event, and hands off to Inventory
        for item in event.items:
            current_domain.process(
                ReserveStock(
                    order_id=event.order_id,
                    product_id=item["product_id"],
                    quantity=item["quantity"],
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


# --8<-- [end:event_handler]
