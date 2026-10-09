# --8<-- [start:lifespan-imports]
from contextlib import asynccontextmanager

from fastapi import FastAPI

from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)

# --8<-- [end:lifespan-imports]
# isort: split

from protean import Domain
from protean.fields import String
from protean.utils.globals import current_domain

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer_name = String(required=True)


# --8<-- [start:lifespan]
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize domain and prepare infrastructure
    domain.init()
    with domain.domain_context():
        domain.setup_database()

    yield

    # Shutdown: release resources
    with domain.domain_context():
        # Any cleanup logic here
        pass


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)
register_exception_handlers(app)
# --8<-- [end:lifespan]


@app.post("/orders")
def place_order(payload: dict) -> dict:
    order = Order(customer_name=payload["customer_name"])
    current_domain.repository_for(Order).add(order)
    return {"id": order.id}


@app.get("/orders/{order_id}")
def get_order(order_id: str) -> dict:
    order = current_domain.repository_for(Order).get(order_id)
    return {"id": order.id, "customer_name": order.customer_name}
