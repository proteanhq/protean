from protean import Domain, current_domain, handle, invariant, use_case
from protean.exceptions import InvalidStateError
from protean.fields import Dict, Float, HasMany, Identifier, Integer, List, String

domain = Domain()


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status = String(default="draft")

    @invariant.post
    def must_have_items(self):
        if not self.items:
            raise ValidationError({"_entity": ["Order must contain at least one item"]})

    def place(self):
        if self.status != "draft":
            raise InvalidStateError(f"Cannot place an order that is {self.status}")
        self.status = "placed"


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, default=1)
    price: Float(min_value=0.0, default=0.0)


@domain.aggregate
class Customer:
    email: String(required=True, max_length=254)


# --8<-- [start:handler]
@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command):
        order = Order(
            customer_id=command.customer_id,
            items=command.items,  # ValidationError if empty
        )
        order.place()  # InvalidStateError if invalid transition
        current_domain.repository_for(Order).add(order)


# --8<-- [end:handler]


# --8<-- [start:service]
@domain.application_service(part_of=Order)
class OrderService:
    @use_case
    def place_order(self, customer_id, items):
        order = Order(customer_id=customer_id, items=items)
        order.place()
        current_domain.repository_for(Order).add(order)
        return order.id


# --8<-- [end:service]


# --8<-- [start:repository]
from protean.exceptions import InvalidOperationError
from protean.utils.query import Q


def load_order(order_id):
    repo = current_domain.repository_for(Order)

    # Absence is an error: let it raise
    order = repo.get(order_id)  # ObjectNotFoundError → 404
    return order


def register_customer(email):
    repo = current_domain.repository_for(Customer)

    # Absence is expected: check gracefully
    if repo.exists(Q(email=email)):
        raise InvalidOperationError("Email already registered")
    repo.add(Customer(email=email))


# --8<-- [end:repository]


# --8<-- [start:fastapi]
from fastapi import FastAPI

from protean.integrations.fastapi import register_exception_handlers

app = FastAPI()
register_exception_handlers(app)
# --8<-- [end:fastapi]

from protean.integrations.fastapi import DomainContextMiddleware

app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})


# --8<-- [start:endpoint]
@app.post("/orders", status_code=201)
async def place_order(payload: dict):
    # ValidationError → 400, ObjectNotFoundError → 404, etc.
    current_domain.process(PlaceOrder(**payload))
    return {"status": "accepted"}


# --8<-- [end:endpoint]


# --8<-- [start:test]
import pytest

from protean.exceptions import ValidationError


def test_order_requires_items():
    with pytest.raises(ValidationError) as exc:
        Order(customer_id="c1", items=[])
    assert "must contain at least one item" in str(exc.value)


# --8<-- [end:test]
