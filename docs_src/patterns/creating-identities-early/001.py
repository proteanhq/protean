from protean import Domain, current_domain, handle
from protean.fields import Auto, Float, Identifier, List

domain = Domain(name="CreatingIdentitiesEarlyOrders")
domain.config["command_processing"] = "sync"


# --8<-- [start:aggregate]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier()
    total: Float()


# Identity is assigned the moment the object is created
with domain.domain_context():
    order = Order(customer_id="cust-789", total=149.99)
    print(order.order_id)  # '9cf4ddc4-2919-4021-bd1a-c8083b5fdda7'
# --8<-- [end:aggregate]

# --8<-- [start:supplied]
# The caller provides the identity explicitly
with domain.domain_context():
    order = Order(
        order_id="ord-a1b2c3d4",
        customer_id="cust-789",
        total=149.99,
    )
    print(order.order_id)  # 'ord-a1b2c3d4'
# --8<-- [end:supplied]


# --8<-- [start:command]
@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    items: List()
    total: Float()


# --8<-- [end:command]


# --8<-- [start:api]
import uuid

from fastapi import FastAPI
from pydantic import BaseModel


class CreateOrderRequest(BaseModel):
    order_id: str | None = None
    customer_id: str
    items: list[str] = []
    total: float


app = FastAPI()


@app.post("/orders")
async def create_order(request: CreateOrderRequest):
    # Option 1: Accept the identity from the client
    order_id = request.order_id

    # Option 2: Generate at the API layer if not provided
    if not order_id:
        order_id = str(uuid.uuid4())

    domain.process(
        PlaceOrder(
            order_id=order_id,
            customer_id=request.customer_id,
            items=request.items,
            total=request.total,
        )
    )

    # The API can return the identity immediately,
    # without waiting for persistence to complete.
    return {"order_id": order_id, "status": "accepted"}


# --8<-- [end:api]


# --8<-- [start:handler]
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)

        # If the order already exists, this is a duplicate command
        existing = repo.get_or_none(command.order_id)
        if existing:
            return  # Idempotent: no-op on duplicate

        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            total=command.total,
        )
        repo.add(order)


# --8<-- [end:handler]
