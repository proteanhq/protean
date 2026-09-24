# Vertical Slice Architecture

A vertical slice cuts through all layers of the architecture for a single use case. Instead of organizing code by technical layer (controllers, services, repositories), each feature is a self-contained slice.

## The Protean command flow as a vertical slice

```
Command (input data)
  ↓
Command Handler (orchestration)
  ↓
Aggregate Method (business logic + state change)
  ↓
Event (record of what happened)
  ↓
Event Handler (side effects)
```

Each layer has a clear responsibility:

| Layer | Responsibility | Example |
|-------|---------------|---------|
| Command | Carry input data with validation | `PlaceOrder(customer_id, product_id, quantity)` |
| Command Handler | Load aggregate, validate context, delegate | Load order, check authorization |
| Aggregate Method | Enforce business rules, mutate state, raise event | Calculate total, set status, raise `OrderPlaced` |
| Event | Immutable record of state change | `OrderPlaced(order_id, total)` |
| Event Handler | React with side effects | Send confirmation, update inventory |

## Creating a new use case

When adding a new feature, create these components in order:

1. **Command** — Define the input contract
2. **Event** — Define what will be recorded
3. **Aggregate method** — Implement the business logic
4. **Command handler** — Wire the command to the aggregate
5. **Event handler** — Add side effects (if needed)

## File organization (Screaming Architecture)

Organize by domain concept, not by technical type:

```
src/
  order/
    place_order.py        # PlaceOrder command + handler
    order_placed.py       # OrderPlaced event
    order.py              # Order aggregate
    handle_order_placed.py  # Event handler for OrderPlaced
```

Not by technical layer:
```
# AVOID
src/
  commands/
    place_order.py
  handlers/
    order_handler.py
  events/
    order_placed.py
```

## Complete examples

See the asset files for complete runnable vertical slices:

- [use_case_basic.py](../assets/use_case_basic.py) — Simple create pattern
- [use_case_with_update.py](../assets/use_case_with_update.py) — Create + update + event handler
- [use_case_with_guards.py](../assets/use_case_with_guards.py) — Authorization and existence checks
