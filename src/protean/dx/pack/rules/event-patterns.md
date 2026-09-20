---
description: Event patterns — raising events, cross-aggregate streams, versioning, and immutability rules
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

## Cross-Aggregate Event Handling via `stream_category`

When an event handler in one aggregate needs to react to events from another aggregate,
use `stream_category` to subscribe to the source aggregate's event stream:

```python
@domain.event_handler(
    part_of=Inventory,
    stream_category=Order.meta_.stream_category,
)
class OrderEventsHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event):
        inventory = self.repository.get(event.product_id)
        inventory.reserve(event.quantity)
        self.repository.add(inventory)
```

The handler's `part_of` points to the **target** aggregate; `stream_category` points to the
**source** aggregate's stream.

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
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
```
