from fastapi import FastAPI

from protean import Domain
from protean.fields import String
from protean.integrations.fastapi import DomainContextMiddleware
from protean.utils.globals import current_domain

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer_name = String(required=True)


# --8<-- [start:module-level]
domain.init()  # Called once at import time

app = FastAPI()
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)
# --8<-- [end:module-level]


@app.post("/orders")
def place_order(payload: dict) -> dict:
    order = Order(customer_name=payload["customer_name"])
    current_domain.repository_for(Order).add(order)
    return {"id": order.id}
