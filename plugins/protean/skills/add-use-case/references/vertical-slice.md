# Vertical Slice Architecture

A vertical slice cuts through all layers of the architecture for a single use case. Instead of organizing code by technical layer (controllers, services, repositories), each feature is a self-contained slice.

## The Protean command flow as a vertical slice

The SKILL.md shows the flow. Each layer has one responsibility:

| Layer | Responsibility | Example |
|-------|---------------|---------|
| Command | Carry input data with validation | `PlaceOrder(customer_id, product_id, quantity)` |
| Command Handler | Load aggregate, validate context, delegate | Load order, check authorization |
| Aggregate Method | Enforce business rules, mutate state, raise event | Calculate total, set status, raise `OrderPlaced` |
| Event | Immutable record of state change | `OrderPlaced(order_id, total)` |
| Event Handler | React with side effects | Send confirmation, issue a command to Inventory |

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
