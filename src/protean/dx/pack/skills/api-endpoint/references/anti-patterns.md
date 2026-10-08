# API Endpoint Anti-patterns

Common mistakes when implementing API endpoints in Protean and how to avoid
them. Each **Wrong** block is shown on purpose and does not run. The
**Correct** blocks build on this domain:

```python
from fastapi import APIRouter
from pydantic import BaseModel
from protean.utils.globals import current_domain


@domain.aggregate
class Order:
    order_id = Identifier(identifier=True)
    customer_id = String(required=True)
    total_amount = Float(min_value=0, max_value=10000)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    total_amount = Float(required=True)


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

## 1. Business Logic in the Endpoint

**Wrong:**
```python
# fragment
@router.post("")
def place_order(body: PlaceOrderRequest):
    if body.total_amount <= 0:
        return JSONResponse(status_code=400, content={"error": "Invalid amount"})
    if body.total_amount > 10000:
        return JSONResponse(status_code=400, content={"error": "Amount too high"})
    command = PlaceOrder(...)
    current_domain.process(command, asynchronous=False)
```

**Correct:** Business rules belong in the aggregate. The endpoint only builds
the command.

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

The aggregate's `total_amount` field enforces the range. A value outside it
raises `ValidationError`, and the client gets a 400.

## 2. Direct Repository Access

**Wrong:**
```python
# fragment
@router.post("")
def place_order(body: PlaceOrderRequest):
    order = Order(order_id=body.order_id, customer_id=body.customer_id)
    current_domain.repository_for(Order).add(order)  # Direct repo access!
```

**Correct:** Always go through `current_domain.process()`. The endpoint builds
a command and lets the handler do the persistence.

## 3. Hand-rolled Middleware or Exception Handlers

**Wrong:**
```python
# fragment
app = FastAPI()


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    with domain.domain_context():
        return await call_next(request)


@app.exception_handler(ObjectNotFoundError)
async def not_found_handler(request: Request, exc: ObjectNotFoundError):
    return JSONResponse(status_code=404, content={"message": str(exc)})
```

These copy what the integration already does, with less: no correlation IDs,
no HTTP wide event, and an error body shape that differs from the rest of the
app.

**Correct:** Use the integration in the app factory.

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

## 4. An `async def` Endpoint That Calls `process()`

**Wrong:**
```python
# fragment
@router.post("", status_code=201)
async def place_order(body: PlaceOrderRequest):
    command = PlaceOrder(**body.model_dump())
    order_id = current_domain.process(command, asynchronous=False)  # Blocks the loop!
    return {"order_id": order_id}
```

`process(..., asynchronous=False)` runs the handler and its database calls
synchronously. Inside an `async def` endpoint that runs on the event loop, so
every other request waits until it finishes.

**Correct:** Write the endpoint as plain `def`, as in pattern 1. FastAPI runs a
`def` endpoint in its thread pool, and the middleware's domain context reaches
it there.

## 5. Calling Handlers Directly

**Wrong:**
```python
# fragment
@router.post("")
def place_order(body: PlaceOrderRequest):
    OrderCommandHandler().place(command)  # Bypasses domain.process!
```

**Correct:** Always use `current_domain.process(command)`. Calling the handler
directly skips command enrichment, event store persistence and the unit of
work.

## 6. Importing the Domain Instead of Using `current_domain`

**Wrong:**
```python
# fragment
from my_app import domain  # Module-level import


@router.post("")
def place_order(body: PlaceOrderRequest):
    domain.process(command)  # Uses the module-level reference
```

**Correct:** Use `current_domain` from `protean.utils.globals`. The middleware
sets it for each request, so the same router works for whichever domain the
request is routed to, and in tests that build their own domain.

## 7. Domain Rules in the Pydantic Model

**Wrong:**
```python
# fragment
class PlaceOrderRequest(BaseModel):
    total_amount: float = Field(..., gt=0, lt=10000)  # Business rule in Pydantic!
```

**Correct:** Pydantic checks format: types, required keys, an email pattern.
Business rules such as amount limits and status changes belong on the command
and the aggregate. The request model at the top of this page checks types only.

## 8. Fat Endpoints with Multiple Operations

**Wrong:**
```python
# fragment
@router.post("")
def place_order(body: PlaceOrderRequest):
    current_domain.process(PlaceOrder(...), asynchronous=False)
    current_domain.process(ReserveStock(...), asynchronous=False)  # Second aggregate!
```

**Correct:** One endpoint, one command. Cross-aggregate work happens through
domain events, not in endpoints.

## Related

- [Request Validation](./request-validation.md) - Proper validation patterns
- [Response Patterns](./response-patterns.md) - HTTP response guidelines
- [command-handler anti-patterns](../../command-handler/references/anti-patterns.md) - Handler-level mistakes
