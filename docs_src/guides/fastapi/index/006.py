# --8<-- [start:imports]
from fastapi import FastAPI

from protean import Domain, handle
from protean.fields import Identifier, String
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)
from protean.utils.globals import current_domain

# --8<-- [end:imports]

# --8<-- [start:domain]
domain = Domain(__file__, name="Ordering")


@domain.aggregate
class Order:
    customer_id = Identifier(required=True)
    status = String(default="PLACED")


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id = Identifier(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order(customer_id=command.customer_id)
        current_domain.repository_for(Order).add(order)


# --8<-- [end:domain]

# --8<-- [start:app]
app = FastAPI()

# 1. Middleware: push domain context per request
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)

# 2. Exception handlers: map domain exceptions to HTTP responses
register_exception_handlers(app)
# --8<-- [end:app]


# --8<-- [start:endpoint]
@app.post("/orders")
def place_order(payload: dict):
    # Correlation ID from X-Correlation-ID header is picked up automatically.
    current_domain.process(PlaceOrder(**payload))
    return {"status": "accepted"}


# --8<-- [end:endpoint]
