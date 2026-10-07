# Cross-Aggregate Event Flow

An event raised by one aggregate leads to a change in another. The event handler sits in the cluster that owns the event and issues a command. The target aggregate's command handler does the write. This is the core DDD pattern for eventual consistency between aggregates.

## Overview

Cross-aggregate event handling enables decoupled communication:
1. Source aggregate raises an event on its own stream
2. An event handler in the source's cluster (`part_of=` the source) reacts and calls `current_domain.process(...)` with a command
3. The command is `part_of` the target aggregate, and the target's command handler loads, changes and persists it

This is the primary mechanism for inter-aggregate coordination without direct coupling. For a flow with several causally dependent steps, use a [process manager](../../process-manager/SKILL.md).

Common use cases:
- Reducing inventory when an order ships
- Initiating payment when an order is placed
- Creating shipments when payment is confirmed
- Earning loyalty points on purchase

## Code

The complete implementation is in [assets/add_event_cross_aggregate.py](../assets/add_event_cross_aggregate.py).

Key highlights:
- Order aggregate raises `OrderShipped` event
- An event handler with `part_of=Order` reacts and issues a `ReduceStock` command
- Inventory's command handler loads Inventory from the repository, calls an aggregate method, and persists
- `ReduceStock` carries the order id, and Inventory skips an order it has already applied
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
- Carries `product_id` and `quantity`, the data Inventory needs

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

### The Command (on target aggregate)

```python
@domain.command(part_of="Inventory")
class ReduceStock:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
```

- Belongs to Inventory, the aggregate it changes
- Carries `order_id` from the event. Events are delivered at least once, so a redelivered event reissues the same command, and the id lets the handler see it has already done the work

### The Target Aggregate

```python
@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    in_stock: Integer(required=True)
    applied_order_ids: List(content_type=String)

    def reduce_stock(self, order_id: str, quantity: int):
        if quantity > self.in_stock:
            raise ValueError("Insufficient stock")
        self.in_stock -= quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]
```

- Business logic (stock validation) lives in the aggregate
- The command handler calls this method. It does NOT inline the logic
- `applied_order_ids` records each order that has reduced the stock. Reducing stock is an update, so the stock level alone cannot show whether an order was applied

### The Target's Command Handler

```python
@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=command.product_id)
        if command.order_id in inventory.applied_order_ids:
            return  # already applied; reducing again would take the stock down twice
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)
```

- Uses `repo.find_by()` to look up inventory by product_id (not by aggregate ID)
- Returns without changes when the order is already applied
- Calls `reduce_stock()` on the aggregate, which keeps business logic in the aggregate

### The Cross-Aggregate Event Handler

```python
@domain.event_handler(part_of=Order)
class InventorySyncHandler:
    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )
```

- `part_of=Order`: the handler sits in the cluster that owns `OrderShipped`
- It does not load or save Inventory. It issues `ReduceStock`, and Inventory's command handler does the write
- The ids in the command come from the event. A fresh `uuid4()` here would make every delivery look new

When a command creates an aggregate, give the new aggregate an id taken from the event. Its command handler calls `repository.get` with that id and adds the aggregate only on `ObjectNotFoundError`. See [split-aggregate](../../split-aggregate/SKILL.md).

## Anti-pattern: a handler in the target's cluster

This is the shape `check` reports as `EVENT_HANDLER_FOREIGN_EVENT`. Do not write it:

```python
# fragment
# Wrong: an Inventory handler that reacts to Order's event
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class ManageInventory:
    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=event.product_id)
        inventory.reduce_stock(event.quantity)
        repo.add(inventory)
```

Move the handler into Order's cluster and issue a command to Inventory, as in the walkthrough.

## File organization

The event handler lives in the **source** aggregate's folder, named after the event it handles. The command and its handler live in the **target** aggregate's folder:

```
src/myapp/
├── order/
│   ├── order.py                 # Order aggregate (raises OrderShipped)
│   ├── order_shipped.py         # OrderShipped event definition
│   └── handle_order_shipped.py  # Event handler (issues ReduceStock)
│
└── inventory/
    ├── inventory.py             # Inventory aggregate
    └── reduce_stock.py          # ReduceStock command + its command handler
```

## When to use cross-aggregate handlers

Use this pattern when:
- A state change in one aggregate should trigger updates in another
- You need eventual consistency between bounded contexts
- You want to decouple aggregates from each other

**Not suitable when:**
- The side effect targets the same aggregate that raised the event (use [same-aggregate flow](./same-aggregate-flow.md))
- You need synchronous, immediate consistency (consider command handlers instead)
- The flow has several causally dependent steps (use a [process manager](../../process-manager/SKILL.md))

## Testing

When testing cross-aggregate event flows:
1. Set up both aggregates (source and target) in the repository, with `event_processing` and `command_processing` set to `"sync"`
2. Trigger the source aggregate's method that raises the event
3. Persist the source aggregate (this dispatches the event)
4. Verify the target aggregate was updated correctly
5. Process the same command again and verify the target did not change a second time

## Related
- [Same-aggregate event flow](./same-aggregate-flow.md) - Handler on the same aggregate
- [Multiple events flow](./multiple-events-flow.md) - Multiple events from one aggregate
- [event-handler skill](../../event-handler/SKILL.md) - Full handler reference
- [command-handler skill](../../command-handler/SKILL.md) - The target's write path
