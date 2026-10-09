---
name: api-endpoint
description: Define FastAPI API endpoints for a Protean application. Endpoints are thin adapters at the domain boundary that translate HTTP requests into domain commands and hand them off via domain.process(). They contain NO business logic. Use when you need to create an API endpoint, define a route, add a REST endpoint, expose a command via HTTP, build a FastAPI handler, connect HTTP to the domain, create a POST/PUT/DELETE endpoint, or wire an HTTP request to a domain command.
license: Apache-2.0
compatibility: Requires Python 3.11+ and protean[server] (installs fastapi)
metadata:
  author: proteanhq
  version: "0.2"
  category: element
---

# API Endpoint

Protean ships a FastAPI integration in `protean.integrations.fastapi`. FastAPI
comes with the `server` extra, so install it first:

```bash
pip install "protean[server]"
```

The integration gives you two pieces. `DomainContextMiddleware` pushes the
domain context for each request, so `current_domain` works inside an endpoint.
`register_exception_handlers` turns six exceptions, five from Protean and
Python's `ValueError`, into HTTP responses. They are listed under
[Status codes](#status-codes). An endpoint needs no `try`/`except` for those.
Any other exception gives a plain 500. One example is `TooManyObjectsError`,
which `repository.find_by` raises when more than one row matches.

## The domain the endpoints use

The endpoints below submit commands to this aggregate and handler. The
handler loads an existing order with `repository.get`, which raises
`ObjectNotFoundError` for an unknown id.

```python
from protean.exceptions import InvalidStateError
from protean.utils.globals import current_domain


@domain.aggregate
class Order:
    order_id = Identifier(identifier=True)
    customer_id = String(required=True)
    total_amount = Float(min_value=0)
    status = String(default="placed")
    cancel_reason = String()

    def cancel(self, reason: str) -> None:
        if self.status == "cancelled":
            raise InvalidStateError("Order is already cancelled")
        self.status = "cancelled"
        self.cancel_reason = reason


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)
    customer_id = String(required=True, max_length=50)
    total_amount = Float(required=True, min_value=0)


@domain.command(part_of=Order)
class CancelOrder:
    order_id = Identifier(required=True)
    reason = String(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> str:
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            total_amount=command.total_amount,
        )
        current_domain.repository_for(Order).add(order)
        return order.order_id

    @handle(CancelOrder)
    def cancel(self, command: CancelOrder) -> str:
        order = current_domain.repository_for(Order).get(command.order_id)
        order.cancel(command.reason)
        current_domain.repository_for(Order).add(order)
        return order.order_id
```

## Basic structure

Put endpoints on an `APIRouter`. Each endpoint builds a command from the
request and passes it to `current_domain.process(..., asynchronous=False)`.

```python
from fastapi import APIRouter
from pydantic import BaseModel


class PlaceOrderRequest(BaseModel):
    order_id: str
    customer_id: str
    total_amount: float


router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", status_code=201)
def place_order(body: PlaceOrderRequest):
    command = PlaceOrder(
        order_id=body.order_id,
        customer_id=body.customer_id,
        total_amount=body.total_amount,
    )
    order_id = current_domain.process(command, asynchronous=False)
    return {"order_id": order_id, "status": "placed"}
```

## The app factory

Build the app in one function. It adds the middleware, registers the
exception handlers, and includes your routers. Pass it an initialized domain.

```python
from fastapi import FastAPI
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)


def create_app(domain: Domain) -> FastAPI:
    app = FastAPI()
    app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})
    register_exception_handlers(app)
    app.include_router(router)
    return app
```

`route_domain_map={"/": domain}` sends every request to one domain. An app
with several bounded contexts maps one URL prefix to each domain instead.

To serve it, initialize the domain and hand the app to uvicorn:

```python
# fragment
import uvicorn

domain.init()
uvicorn.run(create_app(domain), host="127.0.0.1", port=8000)
```

## Key rules

1. **Endpoints are thin adapters.** A write endpoint translates HTTP into a command. It holds no business logic, and it does not change or save aggregates itself. This skill covers write endpoints. For read endpoints, see the `query` and `projection` skills.
2. **Write endpoints as plain `def`.** `current_domain.process(..., asynchronous=False)` is a blocking call. FastAPI runs a `def` endpoint in its thread pool, which keeps that call off the event loop. The domain context from the middleware still reaches the endpoint there. An `async def` endpoint that calls `process()` blocks every other request while it runs.
3. **Use the integration's middleware and exception handlers.** Add `DomainContextMiddleware` and call `register_exception_handlers(app)` in the app factory. Do not write your own.
4. **Always go through `current_domain.process()`.** Never call a handler directly. Import `current_domain` from `protean.utils.globals`.
5. **Pass `asynchronous=False`.** The endpoint then gets the handler's return value, and a domain error such as a missing aggregate is raised inside the request, where the exception handlers can turn it into a 404 or 409.
6. **Build the command from the request.** Map the body fields, and the path parameters, to command fields one by one.
7. **Return the right success code.** 201 for creation, 200 for a change to an existing aggregate.
8. **Let Pydantic check the shape and Protean check the rules.** A Pydantic request model checks types, required keys and formats such as an email pattern. Domain limits, such as a maximum length or a value range, and state rules belong on the command and the aggregate.

## Status codes

`register_exception_handlers` maps these exceptions, and only these, to a
response. Any other exception gives a plain-text 500.

| Exception | Status | Body |
|-----------|:------:|------|
| `ValidationError` | 400 | `{"error": {"<field>": ["<message>", ...]}}` |
| `InvalidDataError` | 400 | `{"error": {"<field>": ["<message>", ...]}}` |
| `ValueError` | 400 | `{"error": "<message>"}` |
| `ObjectNotFoundError` | 404 | `{"error": "<message>"}` |
| `InvalidStateError` | 409 | `{"error": "<message>"}` |
| `InvalidOperationError` | 422 | `{"error": "<message>"}` |

A `ValidationError` also comes from the repository: adding an aggregate whose
id is already stored gives a 400 keyed by the id field.

When a domain context is active, each body in the table also carries
`correlation_id`. It
matches the response's `X-Correlation-ID` header. The middleware pushes a
domain context only for paths that match one of its mapped prefixes, so a
request outside them has no `correlation_id` in its error body.

Two different things can return 422:

- **Protean's `InvalidOperationError`** gives `{"error": "<message>"}`.
- **FastAPI itself** returns 422 before your endpoint runs, when the body does
  not match the Pydantic model (a missing key, or a value Pydantic cannot
  convert to the field's type). That body is `{"detail": [...]}`, with no
  `error` key and no `correlation_id`. Pydantic converts some values in its
  default mode, so `"5"` and `true` pass a `float` field as `5.0` and `1.0`.
  Use `Field(strict=True)` on a field that must reject them.

A value that passes the Pydantic model but breaks a command field rule, such
as a `customer_id` longer than `max_length=50`, gives Protean's 400.

## Endpoint patterns

| Pattern | HTTP Method | Example | Command Source |
|---------|------------|---------|----------------|
| Create resource | POST | `POST /orders` | Body |
| Action on resource | PUT | `PUT /orders/{id}/cancel` | Path + Body |
| Action without body | PUT | `PUT /shipments/{id}/deliver` | Path only |

## Quick example: Path parameters

```python
class CancelOrderRequest(BaseModel):
    reason: str


@router.put("/{order_id}/cancel")
def cancel_order(order_id: str, body: CancelOrderRequest):
    command = CancelOrder(order_id=order_id, reason=body.reason)
    current_domain.process(command, asynchronous=False)
    return {"order_id": order_id, "status": "cancelled"}
```

The order id comes from the path and the reason from the body. An unknown id
gives a 404, and cancelling twice gives a 409, with no error handling in the
endpoint.

## Sync vs async processing

`current_domain.process(command, asynchronous=False)` runs the handler during
the request and returns the handler's result. `current_domain.process(command)`
uses the domain's `command_processing` setting, which is `"async"` by default.
It stores the command and returns its position in the event store, and the
server's engine runs the handler later.

Use `asynchronous=False` when the endpoint needs the handler's result, or
needs a missing aggregate to become a 404. With async processing the endpoint
returns success even if the handler later fails.

## Common mistakes

### Business logic in the endpoint

```python
# fragment
# Wrong! Business logic belongs in the aggregate
@router.post("")
def place_order(body: PlaceOrderRequest):
    if body.total_amount <= 0:  # Business rule in the endpoint!
        return JSONResponse(status_code=400, content={"error": "Invalid amount"})
```

Instead: let the command and the aggregate enforce the rule. The endpoint only builds the command.

### Saving aggregates in the endpoint

```python
# fragment
# Wrong! The endpoint persists the aggregate itself
@router.post("")
def place_order(body: PlaceOrderRequest):
    order = Order(order_id=body.order_id, customer_id=body.customer_id)
    current_domain.repository_for(Order).add(order)  # Direct repo access!
```

Instead: build a command and pass it to `current_domain.process()`. The handler saves the aggregate.

### An `async def` endpoint that calls `process()`

```python
# fragment
# Wrong! process() blocks the event loop for every other request
@router.post("")
async def place_order(body: PlaceOrderRequest):
    current_domain.process(PlaceOrder(**body.model_dump()), asynchronous=False)
```

Instead: write the endpoint as plain `def`.

### Hand-rolled middleware or exception handlers

```python
# fragment
# Wrong! The integration already does this, and adds correlation IDs
@app.middleware("http")
async def domain_context_middleware(request, call_next):
    with domain.domain_context():
        return await call_next(request)
```

Instead: add `DomainContextMiddleware` and call `register_exception_handlers(app)` in the app factory.

### Calling handlers directly

```python
# fragment
# Wrong! Never bypass domain.process()
@router.post("")
def place_order(body: PlaceOrderRequest):
    OrderCommandHandler().place(command)  # Skips enrichment and the event store!
```

Instead: always use `current_domain.process(command, asynchronous=False)`.

## Detailed references

### Concepts
- [Request Validation](references/request-validation.md) - Pydantic models, and the 422 and 400 cases
- [Response Patterns](references/response-patterns.md) - Success responses and the exception-to-status map
- [Testing Endpoints](references/testing-endpoints.md) - Testing your endpoints with `TestClient`
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Complete app](assets/api_endpoint_complete_router.py) - The `create_app` factory and a full router for one aggregate
- [Simple POST](assets/api_endpoint_simple.py) - A router with one POST endpoint
- [Path Parameters](assets/api_endpoint_path_params.py) - A router with path parameters, 404 and 409
- [Pydantic Validation](assets/api_endpoint_with_pydantic.py) - A router with Pydantic request models

### Related Skills
- `command` - Commands are what endpoints construct
- `command-handler` - Command handlers process the commands that endpoints submit
- `aggregate` - The target of commands submitted through endpoints

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
