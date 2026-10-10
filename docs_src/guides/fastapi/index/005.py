from protean import Domain
from protean.exceptions import (
    InvalidDataError,
    InvalidOperationError,
    InvalidStateError,
    ValidationError,
)
from protean.fields import String
from protean.integrations.fastapi import DomainContextMiddleware

# isort: split

# --8<-- [start:example-imports]
from protean.exceptions import ObjectNotFoundError
from protean.utils.globals import current_domain

# --8<-- [end:example-imports]
# isort: split

# --8<-- [start:setup]
from fastapi import FastAPI

from protean.integrations.fastapi import register_exception_handlers

app = FastAPI()
register_exception_handlers(app)
# --8<-- [end:setup]

domain = Domain(name="Identity")


@domain.aggregate
class Customer:
    name = String(required=True, max_length=50)


app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})


# --8<-- [start:example]
@app.get("/customers/{customer_id}")
def get_customer(customer_id: str):
    repo = current_domain.repository_for(Customer)
    customer = repo.get(customer_id)  # Raises ObjectNotFoundError → 404
    return {"id": customer.id, "name": customer.name}


# --8<-- [end:example]

ERRORS = {
    "validation": lambda: ValidationError({"name": ["is required"]}),
    "invalid-data": lambda: InvalidDataError({"name": ["is too long"]}),
    "value": lambda: ValueError("quantity must be positive"),
    "not-found": lambda: ObjectNotFoundError("Customer 42 does not exist"),
    "invalid-state": lambda: InvalidStateError("Order is already shipped"),
    "invalid-operation": lambda: InvalidOperationError("Cannot cancel a paid order"),
}


@app.get("/raise/{kind}")
def raise_error(kind: str):
    raise ERRORS[kind]()
