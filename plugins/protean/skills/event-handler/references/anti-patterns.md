# Event Handler Anti-patterns

Two mistakes are in the "Common mistakes" section of SKILL.md and not repeated here: wrapping a handler in a `UnitOfWork`, and putting business logic in the handler.

The examples on this page use these elements:

```python
@domain.aggregate
class Order:
    product_id: Identifier()
    quantity: Integer()
    status: String(default="placed")
    confirmation_number: String()

@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)

@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

@domain.command(part_of=Order)
class PlaceOrder:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    stock_level: Integer(required=True)
    applied_order_ids: List(content_type=String)

    def reduce_stock(self, order_id, quantity):
        self.stock_level -= quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]

@domain.aggregate
class Task:
    title: String(required=True)

@domain.aggregate
class AuditLog:
    event_type: String(required=True)
```

## 1. Missing part_of and stream_category

**Wrong:**
```python
# fragment
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

Protean raises ``IncorrectUsageError: Event Handler `OrderEventHandler` needs to be associated with an aggregate or a stream``.

## 2. Returning Values from Event Handlers

**Wrong:**
```python
# fragment
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
class OrderConfirmationHandler:
    @handle(OrderPlaced)
    def handle(self, event: OrderPlaced):
        order = domain.repository_for(Order).get(event.order_id)
        order.confirmation_number = "CONF-123"
        domain.repository_for(Order).add(order)
        # No return value - update state instead
```

Event handlers follow fire-and-forget. Return values are discarded. If you need to communicate results, update aggregates or emit new events.

## 3. Using @handle with Command Classes in Event Handler

**Wrong:**
```python
# fragment
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(PlaceOrder)  # This is a COMMAND, not an event!
    def handle(self, command):
        pass
```

An event handler's `@handle` takes an event class, and a command class belongs in a command handler. Protean does not reject this at `init`: it only warns that `PlaceOrder` has no registered handler, and `domain.process(PlaceOrder(...))` never reaches the event handler's method. Move the method to a command handler.

## 4. Expecting Synchronous Execution in Production

**Wrong:**
```python
# fragment
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

## 5. Coupling Event Handler to Multiple Aggregate Repositories

**Avoid:** Updating multiple aggregate roots in a single event handler method.

```python
# fragment
@handle(OrderPlaced)
def handle(self, event):
    # Updating TWO aggregate roots - violates DDD boundaries
    inventory = domain.repository_for(Inventory).get(...)
    inventory.reserve()
    domain.repository_for(Inventory).add(inventory)

    notification = Notification(...)
    domain.repository_for(Notification).add(notification)
```

The Unit of Work does not stop this. On a provider with transactions, such as the SQL databases, it is one database transaction, and it can hold changes to several aggregates; one aggregate per transaction is a design rule.

**Better:** Have the handler issue one command per target aggregate. Each target's command handler then changes its own aggregate. With async command processing, each runs in its own transaction. See [Cross-Aggregate](./cross-aggregate.md).

## 6. Using Plain Strings for stream_category

**Wrong:**
```python
# fragment
@domain.event_handler(part_of=AuditLog, stream_category="task")  # Plain string: never matches
class TaskAuditor:
    @handle("$any")
    def on_any_task_event(self, event): ...
```

**Correct:** Use `Aggregate.meta_.stream_category` to get the fully-qualified stream name.

```python
@domain.event_handler(part_of=AuditLog, stream_category=Task.meta_.stream_category)
class TaskAuditor:
    @handle("$any")
    def on_any_task_event(self, event):
        domain.repository_for(AuditLog).add(AuditLog(event_type=event.__class__.__name__))
```

A stream category is qualified with the domain name, such as `shop::task`. A handler given the plain string `"task"` registers without error and never receives an event.

## 7. Handling Another Cluster's Event (`EVENT_HANDLER_FOREIGN_EVENT`)

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

**Correct:** Put the handler in the cluster that owns the event and hand off with a command, as in [Building a cross-aggregate handler](../SKILL.md#building-a-cross-aggregate-handler).

## Related

- [Same-Aggregate](./same-aggregate.md): Correct same-aggregate handler pattern
- [Cross-Aggregate](./cross-aggregate.md): Correct cross-aggregate handler pattern
- [Error Handling](./error-handling.md): Proper error handling patterns
- `command-handler`: Compare with command handler anti-patterns
