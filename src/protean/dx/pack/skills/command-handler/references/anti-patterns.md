# Command Handler Anti-patterns

Common mistakes when implementing command handlers in Protean and how to avoid them.

The examples on this page use these elements:

```python
from datetime import datetime, timezone

from protean import handle
from protean.fields import DateTime, Identifier, Integer, String

@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    product_id: Identifier()
    quantity: Integer(default=1)
    status: String(default="draft")
    placed_at: DateTime()

    def place(self):
        if self.status != "draft":
            raise ValueError("Cannot place order")
        self.status = "placed"
        self.placed_at = datetime.now(timezone.utc)
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                product_id=self.product_id,
                quantity=self.quantity,
            )
        )

@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
```

## 1. Missing part_of on Handler

**Wrong:**
```python
# fragment
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
    def handle_place_order(self, command: PlaceOrder):
        order = Order(
            order_id=command.order_id,
            product_id=command.product_id,
            quantity=command.quantity,
        )
        order.place()
        domain.repository_for(Order).add(order)
```

Protean raises `IncorrectUsageError` with the message `` Command Handler `OrderCommandHandler` needs to be associated with an Aggregate ``.

## 2. Command and Handler on Different Aggregates

**Wrong:**
```python
# fragment
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
# fragment
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
# fragment
from protean import UnitOfWork

@handle(PlaceOrder)
def handle_place_order(self, command):
    with UnitOfWork():  # Redundant!
        order = Order(order_id=command.order_id)
        domain.repository_for(Order).add(order)
```

**Correct:** The `@handle` decorator already wraps every call in a Unit of Work. A `with UnitOfWork():` inside the handler joins that outer one: it adds no savepoint and does not commit on its own exit, so it only adds noise. The handler in section 1 is the right shape.

## 5. Persisting Multiple Aggregate Roots

**Wrong:**
```python
# fragment
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    order.place()
    domain.repository_for(Order).add(order)

    # Persisting a SECOND aggregate root - bad practice!
    inventory = domain.repository_for(Inventory).get(command.product_id)
    inventory.reserve(command.order_id, command.quantity)
    domain.repository_for(Inventory).add(inventory)
```

This code runs, and both writes commit together, because a Unit of Work can hold changes to several aggregates. Keeping to one aggregate per transaction is a design rule you follow yourself. Breaking it ties the two aggregates' writes to one handler, outside each aggregate's own boundary.

**Correct:** Persist only one aggregate root. The handler in section 1 places the order, and `Order.place()` raises `OrderPlaced`. An event handler in Order's cluster reacts to `OrderPlaced` and issues a command that belongs to Inventory. Inventory's command handler does the write in a transaction separate from the order's, and skips an order it has already applied, so a redelivered event does not reserve stock twice:

```python
from protean import current_domain, handle
from protean.fields import Identifier, Integer, List, String

@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    available: Integer(default=0)
    applied_order_ids: List(content_type=String)

    def reserve(self, order_id, quantity):
        self.available -= quantity
        self.applied_order_ids = self.applied_order_ids + [order_id]

@domain.command(part_of="Inventory")
class ReserveStock:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

@domain.event_handler(part_of=Order)
class OrderInventoryReactions:
    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced):
        current_domain.process(
            ReserveStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )

@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReserveStock)
    def reserve_stock(self, command: ReserveStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)
        if command.order_id in inventory.applied_order_ids:
            return  # already applied; reserving again would double count
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)
```

The `event-handler` skill covers this pattern in its cross-aggregate reference.

## 6. Using @handle with Non-Command Classes

**Wrong:**
```python
# fragment
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(OrderPlaced)  # This is an EVENT, not a command!
    def handle(self, event):
        pass
```

Protean raises `IncorrectUsageError: Method 'handle' in Command Handler 'OrderCommandHandler' is not associated with a command`.

**Correct:** Give `@handle` in a command handler a command class. To react to `OrderPlaced`, write an event handler with `@handle(OrderPlaced)`.

## 7. Command Without part_of

**Wrong:**
```python
# fragment
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
# fragment
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

**Correct:** Keep business logic in the aggregate. The handler only orchestrates, as in section 1: it builds the order and calls `order.place()`, and `Order.place()` checks the status and sets `placed_at`.

## Related

- [Loading Aggregates](./loading-aggregates.md): Proper hydration patterns
- [Unit of Work](./unit-of-work.md): Understanding implicit transactions
- [Error Handling](./error-handling.md): Proper error handling patterns
