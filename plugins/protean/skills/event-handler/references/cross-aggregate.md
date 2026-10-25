# Cross-Aggregate Event Handling

An event handler that reacts to one aggregate's event and changes a different aggregate through a command, following the "Cross-aggregate sync pattern" in SKILL.md.

## Code

The complete implementation is in [assets/event_handler_cross_aggregate.py](../assets/event_handler_cross_aggregate.py).

## Walkthrough

The examples on this page use these elements, a shortened version of the asset:

```python
@domain.aggregate
class Order:
    book_id: Identifier(required=True)
    quantity: Integer(required=True)
    status: String(default="PENDING")

@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)

@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)

@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    in_stock: Integer(required=True)
    applied_order_ids: List(content_type=String)

    def reduce_stock(self, order_id, quantity):
        self.in_stock -= quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]

@domain.command(part_of=Inventory)
class ReserveStock:
    order_id: Identifier(required=True)

@domain.aggregate
class Notification:
    order_id: Identifier(required=True)

@domain.command(part_of=Notification)
class SendConfirmation:
    order_id: Identifier(required=True)
```

### The Event Handler

```python
@domain.event_handler(part_of=Order)
class ManageInventory:
    @handle(OrderShipped)
    def reduce_stock_level(self, event: OrderShipped):
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                book_id=event.book_id,
                quantity=event.quantity,
            )
        )
```

### The Command

```python
@domain.command(part_of="Inventory")
class ReduceStock:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)
```

The command carries everything Inventory needs, so its handler does not load the Order. `order_id` is a deterministic id taken from the event. An order ships one book, so the order id names exactly one stock change.

### The Command Handler

```python
@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(book_id=command.book_id)
        if command.order_id in inventory.applied_order_ids:
            return  # already applied; reducing again would double count
        inventory.reduce_stock(command.order_id, command.quantity)
        repo.add(inventory)
```

### Why the guard?

Events are delivered at least once, so `OrderShipped` can reach the handler twice and issue `ReduceStock` twice. Reducing stock is an update, so Inventory keeps `applied_order_ids` and the command handler checks it before changing anything. SKILL.md's "Making the receiving end safe to repeat" covers the case where the command creates the target, and how to derive one id per write.

### Why find_by?

The command often carries a field that is not the target aggregate's identity (here `book_id`). The repository's `find_by()` method queries by any field and returns exactly one aggregate. It raises `ObjectNotFoundError` when nothing matches and `TooManyObjectsError` when more than one record does.

If you know the aggregate's identity, use `repo.get(id)`.

## Multiple Event Handlers for Same Event

Unlike commands (one handler per command), multiple event handlers can react to the same event. Each one sits in the cluster that owns the event and issues its own command:

```python
@domain.event_handler(part_of=Order)
class ReserveInventory:
    @handle(OrderPlaced)
    def reserve_stock(self, event):
        current_domain.process(ReserveStock(order_id=event.order_id))

@domain.event_handler(part_of=Order)
class OrderNotifier:
    @handle(OrderPlaced)
    def send_confirmation(self, event):
        current_domain.process(SendConfirmation(order_id=event.order_id))
```

Both handlers process `OrderPlaced` independently.

## Related

- [Same-Aggregate](./same-aggregate.md): Handling events from the same aggregate
- [Cross-Aggregate Patterns](./cross-aggregate-patterns.md): Common sync scenarios
- [Eventual Consistency](./eventual-consistency.md): The window between the two writes
- [Anti-patterns](./anti-patterns.md): Common mistakes
- `command-handler`: The write path the handler hands off to
- `process-manager`: Flows with several causally dependent steps
- `event`: Events are the input to event handlers
- `aggregate`: Event handlers are always connected to aggregates
- `event-sourced-aggregate`: Aggregates whose state is rebuilt from their events
