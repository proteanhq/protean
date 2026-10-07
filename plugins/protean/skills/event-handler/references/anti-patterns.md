# Event Handler Anti-patterns

Common mistakes when implementing event handlers in Protean and how to avoid them.

## 1. Missing part_of and stream_category

**Wrong:**
```python
@domain.event_handler  # Missing both part_of and stream_category!
class OrderEventHandler:
    @handle(OrderPlaced)
    def handle(self, event):
        pass
```

**Correct:**
```python
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def handle(self, event):
        pass
```

Protean raises `IncorrectUsageError: Event Handler 'OrderEventHandler' needs to be associated with an aggregate or a stream`.

An event handler must specify at least one of `part_of` or `stream_category`.

## 2. Returning Values from Event Handlers

**Wrong:**
```python
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def handle(self, event: OrderPlaced):
        order = domain.repository_for(Order).get(event.order_id)
        return order  # Return value is discarded!
```

**Correct:**
```python
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def handle(self, event: OrderPlaced):
        order = domain.repository_for(Order).get(event.order_id)
        order.confirmation_number = "CONF-123"
        domain.repository_for(Order).add(order)
        # No return value - update state instead
```

Event handlers follow fire-and-forget. Return values are discarded. If you need to communicate results, update aggregates or emit new events.

## 3. Manually Wrapping in UnitOfWork

**Wrong:**
```python
@handle(OrderPlaced)
def handle_order_placed(self, event):
    with UnitOfWork():  # Redundant!
        order = domain.repository_for(Order).get(event.order_id)
        order.confirm()
        domain.repository_for(Order).add(order)
```

**Correct:** The `@handle` decorator already wraps the method in a UnitOfWork.

```python
@handle(OrderPlaced)
def handle_order_placed(self, event):
    order = domain.repository_for(Order).get(event.order_id)
    order.confirm()
    domain.repository_for(Order).add(order)
```

## 4. Business Logic in the Handler Instead of the Aggregate

**Wrong:**
```python
@handle(OrderPlaced)
def confirm_order(self, event):
    order = domain.repository_for(Order).get(event.order_id)
    # Business logic leaking into handler!
    if order.status != "placed":
        raise ValueError("Only placed orders can be confirmed")
    order.status = "confirmed"
    domain.repository_for(Order).add(order)
```

**Correct:** Keep business logic in the aggregate. Handler only orchestrates.

```python
@handle(OrderPlaced)
def confirm_order(self, event):
    order = domain.repository_for(Order).get(event.order_id)
    order.confirm()  # Business logic in aggregate
    domain.repository_for(Order).add(order)
```

## 5. Using @handle with Command Classes in Event Handler

**Wrong:**
```python
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(PlaceOrder)  # This is a COMMAND, not an event!
    def handle(self, command):
        pass
```

Event handlers handle events. Command handlers handle commands. Protean validates this during domain initialization.

## 6. Expecting Synchronous Execution in Production

**Wrong:**
```python
# In production code
order.place()
domain.repository_for(Order).add(order)
# Assuming event handler has already run here!
updated = domain.repository_for(Inventory).get(inventory_id)
assert updated.in_stock == 90  # May fail in async mode!
```

**Correct:** Event handlers run asynchronously in production. Design for eventual consistency.

```python
# Use event_processing = "sync" only in tests
domain.config["event_processing"] = "sync"
```

## 7. Coupling Event Handler to Multiple Aggregate Repositories

**Avoid:** Updating multiple aggregate roots in a single event handler method.

```python
@handle(OrderPlaced)
def handle(self, event):
    # Updating TWO aggregate roots - violates DDD boundaries
    inventory = domain.repository_for(Inventory).get(...)
    inventory.reserve()
    domain.repository_for(Inventory).add(inventory)

    notification = Notification(...)
    domain.repository_for(Notification).add(notification)
```

**Better:** Have the handler issue one command per target aggregate. Each target's command handler then changes its own aggregate in its own transaction. See [Cross-Aggregate](./cross-aggregate.md).

## 8. Using Plain Strings for stream_category

**Wrong:**
```python
# fragment
@domain.event_handler(part_of=AuditLog, stream_category="task")  # Plain string - may not match!
class TaskAuditor:
    @handle("$any")
    def on_any_task_event(self, event): ...
```

**Correct:** Use `Aggregate.meta_.stream_category` to get the fully-qualified stream name.

```python
@domain.event_handler(part_of=AuditLog, stream_category=Task.meta_.stream_category)
class TaskAuditor:
    @handle("$any")
    def on_any_task_event(self, event): ...
```

Stream categories are module-qualified internally. Using a plain string like `"order"` may not match the actual stream name, which includes the module path. Always use `Aggregate.meta_.stream_category` for reliable event routing.

## 9. Handling Another Cluster's Event (`EVENT_HANDLER_FOREIGN_EVENT`)

**Wrong:** `check` reports this handler as `EVENT_HANDLER_FOREIGN_EVENT`.

```python
# fragment
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class InventorySyncHandler:
    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=event.product_id)
        inventory.reduce_stock(event.quantity)
        repo.add(inventory)
```

The handler belongs to Inventory but reacts to `OrderShipped`, which belongs to Order. The two clusters are coupled directly: Inventory's handler depends on the shape of Order's event, and nothing in Inventory's write path sees the change.

**Correct:** Put the handler in the cluster that owns the event and hand off with a command. Inventory's command handler does the write, and returns without changes for an order it has already applied, because events are delivered at least once.

```python
# fragment
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

@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=command.product_id)
        if command.order_id in inventory.applied_order_ids:
            return  # already applied
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)
```

For a flow with several causally dependent steps, use a process manager. See [process-manager](../../process-manager/SKILL.md).

## Related

- [Same-Aggregate](./same-aggregate.md) - Correct same-aggregate handler pattern
- [Cross-Aggregate](./cross-aggregate.md) - Correct cross-aggregate handler pattern
- [Error Handling](./error-handling.md) - Proper error handling patterns
- `command-handler` - Compare with command handler anti-patterns
