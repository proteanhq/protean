---
description: "Event patterns: raising events, reacting across aggregates, versioning, and immutability rules"
globs: "**/*.py"
---

# Event Patterns

## Raise Events Inside Aggregate Methods

Events are always raised within aggregate methods using `self.raise_()`. Never raise events
outside of aggregates. Mutate state **before** raising the event:

```python
@domain.aggregate
class Order:
    def place(self):
        self.status = "PLACED"
        self.placed_at = datetime.now(UTC)
        self.raise_(OrderPlaced(order_id=self.id, status=self.status))
```

## Commands and Events Are Immutable DTOs

Commands and events carry only data — no behavior, no entities, no aggregates, no `HasOne`
or `HasMany` associations. Use simple fields and value objects only:

```python
# Good — simple fields and value objects
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    total = Float()
    shipping_address = ValueObject(Address)

# Bad — entity reference inside event
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    line_items = HasMany(LineItem)  # Never do this
```

## Reacting to Another Aggregate's Event

When aggregate A raises an event and aggregate B must change, keep the event handler in A's
cluster (`part_of=A`, no `stream_category`). The handler issues a command that is `part_of=B`,
and B's command handler does the write:

```python
@domain.event_handler(part_of=Order)
class OrderEventsHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event):
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
    def reserve_stock(self, command):
        inventory = self.repository.get(command.product_id)
        if command.order_id in inventory.applied_order_ids:
            return  # this order was already applied
        inventory.reserve(command.order_id, command.quantity)
        self.repository.add(inventory)
```

Events are delivered at least once, so the command carries an id taken from the event, and the
command handler returns without changes when it has already applied that id. For a flow with
several dependent steps, use a process manager.

Do not write `@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)`.
`check` reports that handler as `EVENT_HANDLER_FOREIGN_EVENT`.

## Event Versioning

Events use `__version__` (a positive integer, defaults to `1`) for schema evolution. Bump the
version when the event schema changes and use upcasters for backwards-compatible migration:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2
    order_id = Identifier(required=True)
    total = Float()
    currency = String(default="USD")  # Added in v2
```

## `part_of` Uses String References

Commands, events, entities, and value objects use **string references** for `part_of` to avoid
circular imports:

```python
# DTOs — always string references
@domain.event(part_of="Order")
@domain.command(part_of="Order")
@domain.entity(part_of="Order")

# Handlers — class references are OK when in separate files
@domain.command_handler(part_of=Order)
@domain.event_handler(part_of=Order)
```
