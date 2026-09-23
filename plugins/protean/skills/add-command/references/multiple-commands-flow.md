# Multiple Commands Flow

This reference explains how to add multiple command flows to a single aggregate, with a shared handler and router.

## Overview

Most aggregates support multiple operations. Rather than creating separate handlers for each command, use a single handler class with multiple `@handle` methods. This keeps the code organized and follows the Protean convention of one command handler per aggregate.

## Code

The complete implementation is in [assets/add_command_multiple_commands.py](../assets/add_command_multiple_commands.py).

Key highlights:
- Three commands (`PlaceOrder`, `PayOrder`, `CancelOrder`) all part_of the same aggregate
- One `OrderCommandHandler` with three `@handle` methods
- A FastAPI app with three endpoints (POST + two PUTs)
- Mix of create and update patterns within the same handler

## Walkthrough

### Multiple Commands

```python
@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)

@domain.command(part_of="Order")
class PayOrder:
    order_id: Identifier(required=True)
    payment_method: String(required=True)

@domain.command(part_of="Order")
class CancelOrder:
    order_id: Identifier(required=True)
    reason: String(required=True)
```

All commands share `part_of="Order"`. Each command carries only the data needed for its specific action.

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

Key rules:
- **One handler class per aggregate** - Multiple `@handle` methods are fine
- **Each command has exactly one handler** - Protean enforces this
- **All commands must share the same aggregate** - Command's `part_of` must match handler's `part_of`

### Router Pattern

Map each command to an appropriate HTTP verb and route:

| Command | HTTP | Route | Pattern |
|---------|------|-------|---------|
| `PlaceOrder` | POST | `/orders` | Create (body only) |
| `PayOrder` | PUT | `/orders/{id}/pay` | Update (path + body) |
| `CancelOrder` | PUT | `/orders/{id}/cancel` | Update (path + body) |

## Adding a New Command to an Existing Aggregate

When the aggregate already has commands and a handler:

1. **Define the new command** in the aggregate's module:
   ```python
   @domain.command(part_of="Order")
   class RefundOrder:
       order_id: Identifier(required=True)
       refund_amount: Float(required=True)
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
   def refund(self, amount: float):
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

Each transition is triggered by a command and enforced by the aggregate's business logic. The handler simply loads, calls, and persists - it doesn't check states.

## Related

- [Create-aggregate flow](./create-aggregate-flow.md) - Deep dive into the create pattern
- [Update-aggregate flow](./update-aggregate-flow.md) - Deep dive into the update pattern
