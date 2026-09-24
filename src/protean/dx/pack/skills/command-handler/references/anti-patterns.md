# Command Handler Anti-patterns

Common mistakes when implementing command handlers in Protean and how to avoid them.

## 1. Missing part_of on Handler

**Wrong:**
```python
@domain.command_handler  # Missing part_of!
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle(self, command):
        pass
```

**Correct:**
```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle(self, command):
        pass
```

Protean raises `IncorrectUsageError` with the message `` Command Handler `OrderCommandHandler` needs to be associated with an Aggregate ``.

## 2. Command and Handler on Different Aggregates

**Wrong:**
```python
@domain.command(part_of="Shipment")
class ShipOrder:
    order_id: Identifier(required=True)

@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(ShipOrder)  # ShipOrder belongs to Shipment, not Order!
    def handle(self, command):
        pass
```

Protean raises `IncorrectUsageError: Command 'ShipOrder' in Command Handler 'OrderCommandHandler' is not associated with the same aggregate as the Command Handler`.

**Correct:** Command and handler must share the same aggregate.

## 3. Handling the Same Command in Multiple Handlers

**Wrong:**
```python
@domain.command_handler(part_of=Order)
class OrderHandler1:
    @handle(PlaceOrder)
    def handle(self, command):
        pass

@domain.command_handler(part_of=Order)
class OrderHandler2:
    @handle(PlaceOrder)  # Already handled by OrderHandler1!
    def handle(self, command):
        pass
```

Protean raises `NotSupportedError: Command PlaceOrder cannot be handled by multiple handlers`.

**Correct:** Each command has exactly one handler.

## 4. Manually Wrapping in UnitOfWork

**Wrong:**
```python
from protean import UnitOfWork

@handle(PlaceOrder)
def handle_place_order(self, command):
    with UnitOfWork():  # Redundant!
        order = Order(...)
        domain.repository_for(Order).add(order)
```

**Correct:** The `@handle` decorator already wraps the method in a UnitOfWork.

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(...)
    domain.repository_for(Order).add(order)
```

## 5. Persisting Multiple Aggregate Roots

**Wrong:**
```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    order.place()
    domain.repository_for(Order).add(order)

    # Persisting a SECOND aggregate root - bad practice!
    inventory = domain.repository_for(Inventory).get(command.product_id)
    inventory.reserve(quantity=command.quantity)
    domain.repository_for(Inventory).add(inventory)
```

**Correct:** Persist only one aggregate root. Use domain events for cross-aggregate coordination.

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    order.place()  # Raises OrderPlaced event
    domain.repository_for(Order).add(order)
    # Inventory update happens in an event handler that reacts to OrderPlaced
```

## 6. Using @handle with Non-Command Classes

**Wrong:**
```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(OrderPlaced)  # This is an EVENT, not a command!
    def handle(self, event):
        pass
```

Protean raises `IncorrectUsageError: Method 'handle' in Command Handler 'OrderCommandHandler' is not associated with a command`.

**Correct:** Command handlers handle commands. Event handlers handle events.

## 7. Command Without part_of

**Wrong:**
```python
@domain.command  # Missing part_of!
class PlaceOrder:
    order_id: Identifier(required=True)

@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle(self, command):
        pass
```

Protean raises `IncorrectUsageError: Command 'PlaceOrder' in Command Handler 'OrderCommandHandler' is not associated with an aggregate`.

**Correct:** Commands must always have `part_of`.

## 8. Business Logic in the Handler Instead of the Aggregate

**Wrong:**
```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    # Business logic leaking into handler!
    if order.status != "draft":
        raise ValueError("Cannot place order")
    order.status = "placed"
    order.placed_at = datetime.now()
    domain.repository_for(Order).add(order)
```

**Correct:** Keep business logic in the aggregate. Handler only orchestrates.

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    order.place()  # Business logic lives in the aggregate
    domain.repository_for(Order).add(order)
```

## Related

- [Loading Aggregates](./loading-aggregates.md) - Proper hydration patterns
- [Unit of Work](./unit-of-work.md) - Understanding implicit transactions
- [Error Handling](./error-handling.md) - Proper error handling patterns
