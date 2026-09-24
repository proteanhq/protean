# Cross-Aggregate Event Flow

An event handler that belongs to one aggregate but listens to another aggregate's event stream. This is the core DDD pattern for eventual consistency between aggregates.

## Overview

Cross-aggregate event handling enables decoupled communication:
1. Source aggregate raises an event on its own stream
2. Target aggregate's event handler subscribes to the source's stream via `stream_category`
3. Handler reacts by updating the target aggregate

This is the primary mechanism for inter-aggregate coordination without direct coupling.

Common use cases:
- Reducing inventory when an order ships
- Initiating payment when an order is placed
- Creating shipments when payment is confirmed
- Earning loyalty points on purchase

## Code

The complete implementation is in [assets/add_event_cross_aggregate.py](../assets/add_event_cross_aggregate.py).

Key highlights:
- Order aggregate raises `OrderShipped` event
- Inventory's event handler uses `stream_category=Order.meta_.stream_category` to listen to Order events
- Handler loads Inventory from repository, calls an aggregate method, and persists
- No import or reference from Inventory to Order (decoupled via events)

## Walkthrough

### The Event (on source aggregate)

```python
@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
```

- Belongs to Order aggregate
- Carries `product_id` and `quantity` — the data Inventory needs

### The Source Aggregate Method

```python
@domain.aggregate
class Order:
    def ship(self):
        if self.status != "pending":
            raise ValueError(...)
        self.status = "shipped"
        self.raise_(OrderShipped(
            order_id=self.order_id,
            product_id=self.product_id,
            quantity=self.quantity,
        ))
```

- Order knows nothing about Inventory
- It simply raises the event describing what happened

### The Target Aggregate

```python
@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    in_stock: Integer(required=True)

    def reduce_stock(self, quantity: int):
        if quantity > self.in_stock:
            raise ValueError("Insufficient stock")
        self.in_stock -= quantity
```

- Business logic (stock validation) lives in the aggregate
- The handler calls this method — it does NOT inline the logic

### The Cross-Aggregate Handler

```python
@domain.event_handler(
    part_of=Inventory, stream_category=Order.meta_.stream_category
)
class ManageInventory:
    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = domain.repository_for(Inventory)
        inventory = repo._dao.find_by(product_id=event.product_id)
        inventory.reduce_stock(event.quantity)
        repo.add(inventory)
```

- `part_of=Inventory` — handler belongs to Inventory aggregate
- `stream_category=Order.meta_.stream_category` — listens to Order's event stream
- Uses `_dao.find_by()` to look up inventory by product_id (not by aggregate ID)
- Calls `reduce_stock()` on the aggregate — keeps business logic in the aggregate

## Key pattern: stream_category

The `stream_category` parameter is essential for cross-aggregate handlers:

```python
# This handler belongs to Inventory but listens to Order events
@domain.event_handler(
    part_of=Inventory,
    stream_category=Order.meta_.stream_category
)
```

Without `stream_category`, the handler would only see Inventory's own events (which is the same-aggregate pattern).

## File organization

Cross-aggregate handlers live in the **target** aggregate's folder, named after the event they handle:

```
src/myapp/
├── order/
│   ├── order.py            # Order aggregate (raises OrderShipped)
│   └── order_shipped.py    # OrderShipped event definition
│
└── inventory/
    ├── inventory.py             # Inventory aggregate
    └── handle_order_shipped.py  # Cross-aggregate handler (in target folder)
```

## When to use cross-aggregate handlers

Use this pattern when:
- A state change in one aggregate should trigger updates in another
- You need eventual consistency between bounded contexts
- You want to decouple aggregates from each other

**Not suitable when:**
- The side effect targets the same aggregate that raised the event (use [same-aggregate flow](./same-aggregate-flow.md))
- You need synchronous, immediate consistency (consider command handlers instead)

## Testing

When testing cross-aggregate event flows:
1. Set up both aggregates (source and target) in the repository
2. Trigger the source aggregate's method that raises the event
3. Persist the source aggregate (this dispatches the event)
4. Verify the target aggregate was updated correctly

## Related
- [Same-aggregate event flow](./same-aggregate-flow.md) - Handler on the same aggregate
- [Multiple events flow](./multiple-events-flow.md) - Multiple events from one aggregate
- [event-handler skill](../../event-handler/SKILL.md) - Full handler reference including stream_category
