# --8<-- [start:imports]
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from protean import current_domain
from protean.integrations.fastapi import DomainContextMiddleware

# --8<-- [end:imports]
# isort: split
from protean import Domain, handle
from protean.fields import Dict, Identifier, List

domain = Domain(name="Shipping")


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> None:
        domain.repository_for(Order).add(
            Order(customer_id=command.customer_id, items=command.items)
        )


domain.init(traverse=False)


# --8<-- [start:middleware]
app = FastAPI()
router = APIRouter()


class PlaceOrderRequest(BaseModel):
    customer_id: str
    items: list[dict]


app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/orders": domain},
)


@router.post("/orders")
async def place_order(request: PlaceOrderRequest):
    # No need to extract headers: the middleware already did it.
    # The correlation ID flows through automatically.
    current_domain.process(PlaceOrder(**request.model_dump()))


app.include_router(router)
# --8<-- [end:middleware]
