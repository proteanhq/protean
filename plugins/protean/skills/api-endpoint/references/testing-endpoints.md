# Testing Endpoints

How to test your project's FastAPI endpoints with FastAPI's `TestClient`.

## Overview

An endpoint test sends a request through the whole app, middleware and
exception handlers included, and checks the response. `TestClient` makes the
calls synchronously, with no running server. It needs `httpx`:

```bash
pip install "protean[server]" httpx
```

Endpoint tests check three things:

- The endpoint builds the right command from the request.
- A success returns the right status code and body.
- A domain error becomes the right HTTP error.

Test business logic in the domain's own tests.

## The app under test

The tests below run against this domain, router and app factory. In your
project they live in your own modules, for example `myapp/domain.py` and
`myapp/api.py`, and the tests import them.

```python
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)
from protean.utils.globals import current_domain


@domain.aggregate
class Order:
    order_id = Identifier(identifier=True)
    customer_id = String(required=True, max_length=50)
    status = String(default="placed")


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)
    customer_id = String(required=True, max_length=50)


@domain.command(part_of=Order)
class CancelOrder:
    order_id = Identifier(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> str:
        order = Order(order_id=command.order_id, customer_id=command.customer_id)
        current_domain.repository_for(Order).add(order)
        return order.order_id

    @handle(CancelOrder)
    def cancel(self, command: CancelOrder) -> str:
        order = current_domain.repository_for(Order).get(command.order_id)
        order.status = "cancelled"
        current_domain.repository_for(Order).add(order)
        return order.order_id


class PlaceOrderRequest(BaseModel):
    order_id: str
    customer_id: str


router = APIRouter(prefix="/orders")


@router.post("", status_code=201)
def place_order(body: PlaceOrderRequest):
    command = PlaceOrder(order_id=body.order_id, customer_id=body.customer_id)
    order_id = current_domain.process(command, asynchronous=False)
    return {"order_id": order_id, "status": "placed"}


@router.put("/{order_id}/cancel")
def cancel_order(order_id: str):
    current_domain.process(CancelOrder(order_id=order_id), asynchronous=False)
    return {"order_id": order_id, "status": "cancelled"}


def create_app(domain: Domain) -> FastAPI:
    app = FastAPI()
    app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})
    register_exception_handlers(app)
    app.include_router(router)
    return app
```

## Fixtures

`DomainFixture` initializes the domain once per test session and clears the
stores after each test. The `client` fixture builds the app with the same
factory production uses.

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from protean.integrations.pytest import DomainFixture


@pytest.fixture(scope="session")
def app_fixture():
    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


@pytest.fixture
def client():
    return TestClient(create_app(domain))
```

In your project, replace the names this page defined with imports, such as
`from myapp.domain import domain` and `from myapp.api import create_app`.

## What to test

### 1. A success returns 201 and the id

```python
def test_place_order_returns_201(client):
    response = client.post(
        "/orders", json={"order_id": "ORD-001", "customer_id": "CUST-1"}
    )

    assert response.status_code == 201
    assert response.json() == {"order_id": "ORD-001", "status": "placed"}
```

### 2. A Protean validation error returns 400, keyed by field

The body passes the Pydantic model but breaks the command's `max_length=50`.

```python
def test_too_long_customer_id_returns_400(client):
    response = client.post(
        "/orders", json={"order_id": "ORD-002", "customer_id": "C" * 60}
    )

    assert response.status_code == 400
    assert list(response.json()["error"]) == ["customer_id"]
```

### 3. A missing aggregate returns 404

The handler calls `repository.get`, which raises `ObjectNotFoundError` for an
unknown id.

```python
def test_cancel_unknown_order_returns_404(client):
    response = client.put("/orders/ORD-NOPE/cancel")

    assert response.status_code == 404
    assert "error" in response.json()
```

### 4. A body that fails the Pydantic model returns FastAPI's 422

```python
def test_missing_key_returns_422(client):
    response = client.post("/orders", json={"order_id": "ORD-003"})

    assert response.status_code == 422
    assert "detail" in response.json()
```

### 5. Path parameters reach the command

Create the aggregate first, then act on it through the path.

```python
def test_cancel_existing_order_returns_200(client):
    client.post("/orders", json={"order_id": "ORD-004", "customer_id": "CUST-1"})

    response = client.put("/orders/ORD-004/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
```

## TestClient details

- `TestClient` is synchronous. It runs `def` and `async def` endpoints alike.
- The middleware and exception handlers run just as they do in production.
- `json=` sends a JSON body and sets the `Content-Type` header.
- Read the response with `.status_code`, `.json()` and `.text`.

## Related

- [Request Validation](./request-validation.md) - What to validate at the boundary
- [Response Patterns](./response-patterns.md) - Expected response shapes
- [command-handler skill](../../command-handler/SKILL.md) - Testing command handlers
