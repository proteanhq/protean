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

An event handler must specify at least one of `part_of` or `stream_category` (or both for cross-aggregate handlers).

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
        inventory = domain.repository_for(Inventory).get(event.inventory_id)
        inventory.reserve()
        domain.repository_for(Inventory).add(inventory)
```

**Correct:** The `@handle` decorator already wraps the method in a UnitOfWork.

```python
@handle(OrderPlaced)
def handle_order_placed(self, event):
    inventory = domain.repository_for(Inventory).get(event.inventory_id)
    inventory.reserve()
    domain.repository_for(Inventory).add(inventory)
```

## 4. Business Logic in the Handler Instead of the Aggregate

**Wrong:**
```python
@handle(OrderShipped)
def reduce_stock(self, event):
    inventory = domain.repository_for(Inventory).get(event.inventory_id)
    # Business logic leaking into handler!
    if inventory.in_stock < event.quantity:
        raise ValueError("Not enough stock")
    inventory.in_stock -= event.quantity
    domain.repository_for(Inventory).add(inventory)
```

**Correct:** Keep business logic in the aggregate. Handler only orchestrates.

```python
@handle(OrderShipped)
def reduce_stock(self, event):
    inventory = domain.repository_for(Inventory).get(event.inventory_id)
    inventory.reduce_stock(event.quantity)  # Business logic in aggregate
    domain.repository_for(Inventory).add(inventory)
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

**Better:** Use separate event handlers for separate aggregate updates, or have the handler update only the aggregate it belongs to and raise further events if needed.

## 8. Using Plain Strings for stream_category

**Wrong:**
```python
@domain.event_handler(part_of=Inventory, stream_category="order")  # Plain string - may not match!
class ManageInventory:
    ...
```

**Correct:** Use `Aggregate.meta_.stream_category` to get the fully-qualified stream name.

```python
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class ManageInventory:
    ...
```

Stream categories are module-qualified internally. Using a plain string like `"order"` may not match the actual stream name, which includes the module path. Always use `Aggregate.meta_.stream_category` for reliable event routing.

## Related

- [Same-Aggregate](./same-aggregate.md) - Correct same-aggregate handler pattern
- [Cross-Aggregate](./cross-aggregate.md) - Correct cross-aggregate handler pattern
- [Error Handling](./error-handling.md) - Proper error handling patterns
- `command-handler` - Compare with command handler anti-patterns
