# Multiple Commands Flow

One `Order` aggregate takes three commands, `PlaceOrder`, `PayOrder` and `CancelOrder`. One `OrderCommandHandler` handles all three, mixing the create and update patterns, and one FastAPI app exposes them.

## Walkthrough

### The Aggregate

The commands below all act on one `Order` aggregate:

```python
from decimal import Decimal as D


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Decimal(precision=19, scale=4)
    status: String(default="draft")
    payment_method: String()
    cancel_reason: String()

    def place(self, total_amount: D):
        self.total_amount = total_amount
        self.status = "placed"

    def pay(self, payment_method: str):
        if self.status != "placed":
            raise ValueError(f"Cannot pay for order in '{self.status}' status")
        self.payment_method = payment_method
        self.status = "paid"

    def cancel(self, reason: str):
        if self.status in ("paid", "cancelled"):
            raise ValueError(f"Cannot cancel order in '{self.status}' status")
        self.status = "cancelled"
        self.cancel_reason = reason
```

### Multiple Commands

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Decimal(precision=19, scale=4, required=True)

@domain.command(part_of="Order")
class PayOrder:
    order_id: Identifier(required=True)
    payment_method: String(required=True)

@domain.command(part_of="Order")
class CancelOrder:
    order_id: Identifier(required=True)
    reason: String(required=True)
```

### Shared Handler

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        # CREATE pattern: construct + call method + persist
        ...

    @handle(PayOrder)
    def handle_pay_order(self, command: PayOrder):
        # UPDATE pattern: load + call method + persist
        ...

    @handle(CancelOrder)
    def handle_cancel_order(self, command: CancelOrder):
        # UPDATE pattern: load + call method + persist
        ...
```

Every command the handler handles must have the same `part_of` as the handler.

### Router Pattern

Map each command to an appropriate HTTP verb and route:

| Command | HTTP | Route | Pattern |
|---------|------|-------|---------|
| `PlaceOrder` | POST | `/orders` | Create (body only) |
| `PayOrder` | PUT | `/orders/{id}/pay` | Update (path + body) |
| `CancelOrder` | PUT | `/orders/{id}/cancel` | Update (path + body) |

All endpoints live on one FastAPI app. The middleware gives each request a domain context, so `current_domain` works in the endpoints:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from protean.utils.globals import current_domain


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wire the commands and handlers once, before the app takes requests
    domain.init()
    try:
        yield
    finally:
        # Release the adapter connections on shutdown, even after an error
        domain.close()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    with domain.domain_context():
        return await call_next(request)
```

## Adding a New Command to an Existing Aggregate

When the aggregate already has commands and a handler:

1. **Define the new command** in the aggregate's module:
   ```python
   @domain.command(part_of="Order")
   class RefundOrder:
       order_id: Identifier(required=True)
       refund_amount: Decimal(precision=19, scale=4, required=True)
   ```

2. **Add a `@handle` method** to the existing handler:
   ```python
   @handle(RefundOrder)
   def handle_refund(self, command: RefundOrder):
       order = domain.repository_for(Order).get(command.order_id)
       order.refund(amount=command.refund_amount)
       domain.repository_for(Order).add(order)
       return order.order_id
   ```

3. **Add the aggregate method** (if it doesn't exist):
   ```python
   def refund(self, amount: D):
       if self.status != "paid":
           raise ValueError("Can only refund paid orders")
       self.status = "refunded"
   ```

4. **Add the API endpoint**:
   ```python
   @app.put("/orders/{order_id}/refund")
   async def refund_order(order_id: str, request: Request):
       payload = await request.json()
       command = RefundOrder(
           order_id=order_id,
           refund_amount=payload["refund_amount"],
       )
       result = current_domain.process(command, asynchronous=False)
       return JSONResponse(content={"order_id": result, "status": "refunded"})
   ```

## State Transitions

The Order example demonstrates a typical state machine:

```
draft → placed → paid → (terminal)
  ↓        ↓
cancelled  cancelled
```

Each transition is triggered by a command and enforced by the aggregate's business logic. The handler loads, calls and persists. It does not check states.

## Related

- [Create-aggregate flow](./create-aggregate-flow.md): Deep dive into the create pattern
- [Update-aggregate flow](./update-aggregate-flow.md): Deep dive into the update pattern
