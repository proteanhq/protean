---
description: Handler patterns — UnitOfWork, @handle decorator, thin orchestration, error handling, and return value rules
globs: "**/*.py"
---

# Handler Patterns

## Handlers Are Thin Orchestrators

Command handlers, event handlers, and projectors are **thin orchestrators** — they load aggregates,
call domain methods, and persist. Business logic (validation, state transitions, calculations)
belongs in **aggregate methods**, not handlers.

```python
# Good — handler delegates to aggregate
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(buyer_id=command.buyer_id, items=command.items)
    self.repository.add(order)

# Bad — business logic leaks into handler
@handle(PlaceOrder)
def place_order(self, command):
    if len(command.items) == 0:
        raise ValidationError("Order must have items")
    total = sum(item.price * item.qty for item in command.items)
    order = Order(buyer_id=command.buyer_id, total=total, status="PLACED")
    self.repository.add(order)
```

## Implicit UnitOfWork — Never Wrap Manually

Command handlers, event handlers, projectors, and application services all run within an
**implicit UnitOfWork**. Never manually wrap in `with UnitOfWork()`:

```python
# Good — implicit UoW
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(buyer_id=command.buyer_id)
    self.repository.add(order)

# Bad — manual UoW wrapping
@handle(PlaceOrder)
def place_order(self, command):
    with UnitOfWork():  # Never do this
        order = Order.create(buyer_id=command.buyer_id)
        self.repository.add(order)
```

## `@handle` Decorator

Import `handle` from `protean` and use it to wire handler methods to commands or events:

```python
from protean import handle

@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command):
        ...

@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class OrderEventsHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event):
        ...
```

Projectors use `@on` (alias for `@handle`) imported from `protean.core.projector`:

```python
from protean.core.projector import on

@domain.projector(projector_for=OrderSummary, stream_categories=[Order.meta_.stream_category])
class OrderSummaryProjector:
    @on(OrderPlaced)
    def on_order_placed(self, event):
        ...
```

## Event Handlers Do Not Return Values

Event handlers are fire-and-forget — they do **not** return values. Command handlers may return
values in synchronous mode, but event handlers never do:

```python
# Command handler — return value OK in sync mode
@handle(PlaceOrder)
def place_order(self, command):
    order = Order.create(...)
    self.repository.add(order)
    return order  # OK

# Event handler — no return value
@handle(OrderPlaced)
def on_order_placed(self, event):
    inventory.reserve(event.item_id, event.quantity)
    self.repository.add(inventory)
    # No return
```

## `handle_error` for Async Error Recovery

Handlers can override `handle_error` as a classmethod for custom error recovery during
asynchronous processing:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command):
        ...

    @classmethod
    def handle_error(cls, exc, message):
        # Custom recovery logic for async failures
        logger.error(f"Failed to process {message}: {exc}")
```
