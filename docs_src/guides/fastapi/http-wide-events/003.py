# --8<-- [start:imports]
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from protean.utils.globals import current_domain
from protean.utils.logging import bind_event_context

# --8<-- [end:imports]
# isort: split

from fastapi import FastAPI

from protean import Domain, handle
from protean.fields import Identifier, String
from protean.integrations.fastapi import DomainContextMiddleware

domain = Domain(
    name="Ordering",
    config={"command_processing": "sync", "event_processing": "sync"},
)


@domain.aggregate
class Order:
    customer_id = Identifier(required=True)
    book_id = String(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id = Identifier(required=True)
    book_id = String(required=True)


@domain.command_handler(part_of=Order)
class PlaceOrderHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order(customer_id=command.customer_id, book_id=command.book_id)
        current_domain.repository_for(Order).add(order)


# --8<-- [start:context]
class PlaceOrderRequest(BaseModel):
    customer_id: str
    book_id: str
    device_platform: str


@dataclass
class User:
    id: str
    tier: str


def get_user() -> User:
    # Stands in for your authentication dependency.
    return User(id="user-42", tier="gold")


# --8<-- [end:context]


# --8<-- [start:endpoint]
router = APIRouter()


@router.post("/orders")
async def place_order(
    request: PlaceOrderRequest, user: Annotated[User, Depends(get_user)]
):
    bind_event_context(
        user_id=user.id,
        user_tier=user.tier,
        device_platform=request.device_platform,
    )
    current_domain.process(
        PlaceOrder(**request.model_dump(exclude={"device_platform"}))
    )
    return {"ok": True}


# --8<-- [end:endpoint]


@router.get("/spoof")
def spoof_status() -> dict:
    bind_event_context(http_status=999, request_id="forged", user_id="user-42")
    return {"ok": True}


app = FastAPI()
app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})
app.include_router(router)
