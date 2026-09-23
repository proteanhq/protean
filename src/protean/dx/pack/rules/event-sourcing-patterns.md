---
description: Event sourcing patterns — @apply handlers, state mutation, temporal queries, and replay rules
globs: "**/*.py"
---

# Event Sourcing Patterns

## `@apply` Is the Single Source of Truth

For event-sourced aggregates (`event_sourced=True`), all state mutations happen in
`@apply` handlers — never in business methods directly:

```python
@domain.aggregate(event_sourced=True)
class Order:
    def place(self, items):
        # Validate and raise — do NOT mutate state here
        if not items:
            raise ValueError("Cannot place empty order")
        self.raise_(OrderPlaced(order_id=self.id, items=items))

    @apply
    def on_order_placed(self, event: OrderPlaced) -> None:
        # ALL state mutation happens here
        self.status = "PLACED"
        self.item_count = len(event.items)
```

The `@apply` handler runs both during live event raising AND during replay from the
event store. This guarantees consistent state reconstruction.

## Business Methods Validate and Raise

Business methods on event-sourced aggregates:
1. Validate preconditions (state guards)
2. Call `self.raise_(Event(...))` with the relevant data
3. **Never** mutate `self.field` directly

## Factory Methods for Creation

Use `@classmethod` factories that raise creation events:

```python
@classmethod
def create(cls, customer_id: str) -> "Order":
    order = cls(customer_id=customer_id)
    order.raise_(OrderCreated(order_id=order.id, customer_id=customer_id))
    return order
```

## Temporal Aggregates Are Read-Only

Aggregates loaded at a specific version or point-in-time cannot raise events:

```python
order = repo.get(order_id, at_version=5)
order.cancel()  # Raises IncorrectUsageError
```

## Every Event Needs an `@apply` Handler

If you `raise_(SomeEvent(...))` without a corresponding `@apply` handler, you get
a runtime error. There is no silent fallback.
