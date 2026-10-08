from fastapi import FastAPI

from protean import Domain, current_domain, handle
from protean.fields import Float, HasMany, Identifier, Integer, List, String

domain = Domain(
    name="Shop",
    config={"command_processing": "sync", "event_processing": "sync"},
)
app = FastAPI()


@domain.entity(part_of="Order")
class OrderItem:
    product_id = Identifier(required=True)
    quantity = Integer(min_value=1, default=1)


@domain.aggregate
class Order:
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float()
    items = HasMany(OrderItem)

    def add_item(self, product_id, quantity=1):
        self.add_items(OrderItem(product_id=product_id, quantity=quantity))

    def place(self):
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_id=self.customer_id,
                total=self.total,
                item_count=len(self.items),
            )
        )


# --8<-- [start:command-handler]
# 1. Define the command
@domain.command(part_of=Order)
class PlaceOrder:
    customer_id = Identifier(required=True)
    items = List(required=True)
    total = Float(required=True)


# 2. Create a command handler
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order(
            customer_id=command.customer_id,
            total=command.total,
        )
        for item in command.items:
            order.add_item(**item)
        current_domain.repository_for(Order).add(order)


# --8<-- [end:command-handler]


# --8<-- [start:endpoint]
@app.post("/orders", status_code=201)
async def create_order(payload: dict):
    current_domain.process(PlaceOrder(**payload))
    return {"status": "accepted"}


# --8<-- [end:endpoint]


# --8<-- [start:event]
@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    total = Float()
    item_count = Integer()


# --8<-- [end:event]


# --8<-- [start:projection]
# Define a read model
@domain.projection
class OrderSummary:
    order_id = Identifier(identifier=True)
    customer_id = Identifier()
    total = Float()
    status = String()
    item_count = Integer()


# Populate it with a projector
@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced):
        current_domain.repository_for(OrderSummary).add(
            OrderSummary(
                order_id=event.order_id,
                customer_id=event.customer_id,
                total=event.total,
                status="placed",
                item_count=event.item_count,
            )
        )


# --8<-- [end:projection]
