# --8<-- [start:domain]
from protean import Domain, handle
from protean.fields import Auto, Float, Identifier, Integer, String
from protean.utils.globals import current_domain

domain = Domain(name="ecommerce")


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    product_id = Identifier(required=True)
    quantity = Integer(default=1)
    status = String(default="draft")
    total = Float(default=0.0)

    def place(self):
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                product_id=self.product_id,
                quantity=self.quantity,
                total=self.total,
            )
        )


@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    product_id = Identifier(required=True)
    quantity = Integer(required=True)
    total = Float(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    product_id = Identifier(required=True)
    quantity = Integer(default=1)
    total = Float(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            product_id=command.product_id,
            quantity=command.quantity,
            total=command.total,
        )
        order.place()
        repo.add(order)


@domain.aggregate
class Inventory:
    product_id = Identifier(identifier=True)
    available_quantity = Integer(default=0)
    reserved_quantity = Integer(default=0)

    def reserve(self, order_id, quantity):
        self.available_quantity -= quantity
        self.reserved_quantity += quantity
        self.raise_(
            InventoryReserved(
                product_id=self.product_id, order_id=order_id, quantity=quantity
            )
        )


@domain.event(part_of=Inventory)
class InventoryReserved:
    product_id = Identifier(required=True)
    order_id = Identifier(required=True)
    quantity = Integer(required=True)


@domain.event_handler(part_of=Inventory, stream_category="ecommerce::order")
class InventoryEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(event.product_id)
        inventory.reserve(order_id=event.order_id, quantity=event.quantity)
        repo.add(inventory)


@domain.projection
class OrderDashboard:
    order_id = Identifier(identifier=True)
    customer_id = Identifier()
    status = String()
    total = Float()


@domain.projector(projector_for=OrderDashboard, aggregates=[Order])
class OrderDashboardProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderDashboard)
        repo.add(
            OrderDashboard(
                order_id=event.order_id,
                customer_id=event.customer_id,
                status="placed",
                total=event.total,
            )
        )


# --8<-- [end:domain]
