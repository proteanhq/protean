from protean import Domain, current_domain, handle
from protean.fields import Identifier, String

domain = Domain(name="Sales")
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.aggregate
class Order:
    customer_id: String(required=True)
    status: String(default="new")

    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(order_id=self.id))


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: String(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order(customer_id=command.customer_id)
        order.place()
        current_domain.repository_for(Order).add(order)


# --8<-- [start:middleware]
from fastapi import FastAPI

from protean.integrations.fastapi import DomainContextMiddleware

app = FastAPI()

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)
# --8<-- [end:middleware]


# --8<-- [start:endpoint]
from fastapi import Request


@app.post("/orders")
async def create_order(request: Request, payload: dict):
    request_id = request.headers.get("X-Request-Id")
    current_domain.process(
        PlaceOrder(**payload),
        correlation_id=request_id,  # Thread through the chain
    )


# --8<-- [end:endpoint]
