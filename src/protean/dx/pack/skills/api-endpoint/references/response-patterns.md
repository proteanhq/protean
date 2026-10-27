# Response Patterns

The examples on this page use this aggregate, command and handler:

```python
from decimal import Decimal as D

from fastapi import APIRouter
from pydantic import BaseModel
from protean import current_domain


@domain.aggregate
class Order:
    order_id = Identifier(identifier=True)
    customer_id = String(required=True)
    total_amount = Decimal(precision=19, scale=4, min_value=0)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    total_amount = Decimal(precision=19, scale=4, required=True, min_value=0)


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
    total_amount: D


router = APIRouter(prefix="/orders")
```

## Success status codes

| Operation | Status Code | When |
|-----------|------------|------|
| Resource created | 201 Created | POST that creates a new aggregate |
| Action performed | 200 OK | PUT/POST that changes an existing aggregate |
| Accepted for processing | 202 Accepted | Async command processing |

### Synchronous processing (`asynchronous=False`)

With `asynchronous=False`, `process()` returns the handler's return value, here
the order id. FastAPI serializes the dict the endpoint returns and uses the
decorator's `status_code`, as in the skill's basic structure.

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

The app factory in
[assets/api_endpoint_complete_router.py](../assets/api_endpoint_complete_router.py)
registers the integration's exception handlers. They map these exceptions, and
only these, to a status code and a JSON body:

| Exception | Status | Body |
|-----------|:------:|------|
| `ValidationError` | 400 | `{"error": {"<field>": ["<message>", ...]}}` |
| `InvalidDataError` | 400 | `{"error": {"<field>": ["<message>", ...]}}` |
| `ValueError` | 400 | `{"error": "<message>"}` |
| `ObjectNotFoundError` | 404 | `{"error": "<message>"}` |
| `InvalidStateError` | 409 | `{"error": "<message>"}` |
| `InvalidOperationError` | 422 | `{"error": "<message>"}` |

A 400 from a field rule, inside a domain context, carries the same
`correlation_id` as the `X-Correlation-ID` response header:

```json
{
  "error": {"total_amount": ["Input should be greater than or equal to 0"]},
  "correlation_id": "b2360bdd5476468e8972ae27f4996194"
}
```

A 404 needs two things in the handler path. The handler must load the
aggregate with `repository.get(id)` or `repository.find_by(...)`, which
raise `ObjectNotFoundError` when nothing matches. A query through
`repository.query` returns an empty result instead. And the endpoint must pass
`asynchronous=False`, so the handler runs inside the request.

## Related

- [Request Validation](./request-validation.md): Input validation patterns
- [Testing Endpoints](./testing-endpoints.md): Checking status codes in tests
- [Anti-patterns](./anti-patterns.md): Response anti-patterns
