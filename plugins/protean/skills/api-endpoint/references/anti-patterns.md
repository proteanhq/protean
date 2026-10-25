# API Endpoint Anti-patterns

Each **Wrong** block is shown on purpose and does not run. The **Correct**
block builds on this domain:

```python
from decimal import Decimal as D

from fastapi import APIRouter
from pydantic import BaseModel
from protean.utils.globals import current_domain


@domain.aggregate
class Order:
    order_id = Identifier(identifier=True)
    customer_id = String(required=True)
    total_amount = Decimal(precision=19, scale=4, min_value=0, max_value=10000)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    total_amount = Decimal(precision=19, scale=4, required=True)


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

## 2. Hand-rolled Middleware or Exception Handlers

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

The integration already provides both. The hand-written versions leave out
correlation IDs and the HTTP wide event, and their error body has a different
shape from the rest of the app.

**Correct:** Add `DomainContextMiddleware` and call
`register_exception_handlers(app)` in the app factory, as in
[assets/api_endpoint_complete_router.py](../assets/api_endpoint_complete_router.py).

## 3. Importing the Domain Instead of Using `current_domain`

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

## 4. Domain Rules in the Pydantic Model

**Wrong:**
```python
# fragment
class PlaceOrderRequest(BaseModel):
    total_amount: D = Field(..., gt=0, lt=10000)  # Business rule in Pydantic!
```

**Correct:** Pydantic checks format: types, required keys, an email pattern.
Business rules such as amount limits and status changes belong on the command
and the aggregate. The request model at the top of this page checks types only.

## 5. Fat Endpoints with Multiple Operations

**Wrong:**
```python
# fragment
@router.post("")
def place_order(body: PlaceOrderRequest):
    current_domain.process(PlaceOrder(...), asynchronous=False)
    current_domain.process(ReserveStock(...), asynchronous=False)  # Second aggregate!
```

**Correct:** One endpoint, one command. Cross-aggregate work happens through
domain events. An event handler reacts to the first aggregate's event and
changes the second.

## Related

- [Request Validation](./request-validation.md): Proper validation patterns
- [Response Patterns](./response-patterns.md): HTTP response guidelines
- [command-handler anti-patterns](../../command-handler/references/anti-patterns.md): Handler-level mistakes
