# Response Patterns

HTTP response structure and status codes for Protean API endpoints.

## Overview

An endpoint returns a short confirmation on success. On failure it returns
nothing itself. A domain exception propagates out of the endpoint, and the
handlers that `register_exception_handlers` adds turn it into the response.
Those handlers cover the six exceptions in the table below. Any other
exception gives a plain-text 500.

The examples on this page use this aggregate, command and handler:

```python
from fastapi import APIRouter
from pydantic import BaseModel
from protean.utils.globals import current_domain


@domain.aggregate
class Order:
    order_id = Identifier(identifier=True)
    customer_id = String(required=True)
    total_amount = Float(min_value=0)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    total_amount = Float(required=True, min_value=0)


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


class PlaceOrderRequest(BaseModel):
    order_id: str
    customer_id: str
    total_amount: float


router = APIRouter(prefix="/orders")
```

## Success status codes

| Operation | Status Code | When |
|-----------|------------|------|
| Resource created | 201 Created | POST that creates a new aggregate |
| Action performed | 200 OK | PUT/POST that changes an existing aggregate |
| Accepted for processing | 202 Accepted | Async command processing |

### Synchronous processing (`asynchronous=False`)

```python
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

The handler's return value, here the order id, comes back from `process()`.
FastAPI serializes the returned dict and uses the decorator's `status_code`.

### Asynchronous processing

```python
@router.post("/async", status_code=202)
def place_order_async(body: PlaceOrderRequest):
    command = PlaceOrder(
        order_id=body.order_id,
        customer_id=body.customer_id,
        total_amount=body.total_amount,
    )
    position = current_domain.process(command)
    return {"status": "accepted", "position": position}
```

`process(command)` with no `asynchronous` argument follows the domain's
`command_processing` setting. Protean's default is `"async"`. Then the return
value is the command's position in the event store, not the handler result.
The handler runs later, so a failure in it does not reach this response. A
domain configured with `command_processing = "sync"` runs the handler during
the request and returns its result, as `asynchronous=False` does.

## Error responses

Register the integration's exception handlers in the app factory. The
factory is in
[assets/api_endpoint_complete_router.py](../assets/api_endpoint_complete_router.py).
The handlers map these exceptions, and only these, to a status code and a JSON
body:

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

When a domain context is active, each error body in the table also carries
`correlation_id`, the same value as the `X-Correlation-ID` response header.
`DomainContextMiddleware` pushes that context for each request whose path
matches one of its mapped prefixes. A request outside those prefixes runs
without a domain context, and its error body has no `correlation_id`:

```json
{
  "error": {"total_amount": ["Input should be greater than or equal to 0"]},
  "correlation_id": "b2360bdd5476468e8972ae27f4996194"
}
```

FastAPI also returns 422 on its own, before the endpoint runs, when the body
does not match the Pydantic model. That body is `{"detail": [...]}` and has no
`error` key and no `correlation_id`. See
[Request Validation](./request-validation.md).

A 404 needs two things in the handler path. The handler must load the
aggregate with `repository.get(id)` or `repository.find_by(...)`, which
raise `ObjectNotFoundError` when nothing matches. A query through
`repository.query` returns an empty result instead. And the endpoint must pass
`asynchronous=False`, so the handler runs inside the request.

`find_by` raises `TooManyObjectsError` when more than one row matches. The
exception handlers do not map that exception, so the client gets a 500.

## Related

- [Request Validation](./request-validation.md) - Input validation patterns
- [Testing Endpoints](./testing-endpoints.md) - Checking status codes in tests
- [Anti-patterns](./anti-patterns.md) - Response anti-patterns
