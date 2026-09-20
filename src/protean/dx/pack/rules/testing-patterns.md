---
description: Testing patterns — sync processing, avoiding mocks, event assertions, and what not to test
globs: "**/test_*.py,**/tests/**/*.py"
---

# Testing Patterns

## Use Synchronous Processing in Tests

Configure synchronous processing so events and commands are handled inline during tests:

```python
# In conftest.py or test setup
domain.config["event_processing"] = "sync"

# For subscriber tests
domain.config["message_processing"] = "sync"
```

This makes tests deterministic — no need to wait for async handlers.

## Avoid Mocks — Use Real Domain Elements

Use Protean's in-memory repositories and synchronous event processing instead of mocks.
Construct real aggregates, value objects, commands, and events. Reserve mocks only for
truly external dependencies (third-party APIs, email services):

```python
# Good — real domain elements with in-memory adapters
order = Order.create(buyer_id="user-1", items=[...])
repo = domain.repository_for(Order)
repo.add(order)
retrieved = repo.get(order.id)
assert retrieved.status == "PLACED"

# Bad — mocking the repository
mock_repo = Mock()
mock_repo.get.return_value = Order(status="PLACED")
```

## Assert Events via `_events`

Verify events raised by aggregate methods using the `_events` list. Check both the event
type and field values:

```python
order = Order.create(buyer_id="user-1")
order.place()

assert len(order._events) == 1
assert isinstance(order._events[0], OrderPlaced)
assert order._events[0].order_id == order.id
assert order._events[0].status == "PLACED"
```

Use `_events.clear()` to isolate event assertions between method calls:

```python
order.place()
assert len(order._events) == 1  # OrderPlaced

order._events.clear()

order.ship()
assert len(order._events) == 1  # OrderShipped, not OrderPlaced + OrderShipped
```

## Skip Framework-Guaranteed Behavior

Do **not** write tests for things the framework guarantees:

- Value object immutability
- Command/event immutability
- Field-level type coercion and validation (e.g., `required=True` raising errors)
- Element registration with the domain
- `meta_.part_of` associations
- `.payload` access on events/commands

Instead, focus tests on **your** business logic:

- Aggregate method behavior and state transitions
- Invariant enforcement with domain-specific data
- Event handler side effects
- Cross-aggregate coordination flows
- Edge cases in your domain rules

## Test Full Command Flows

For integration tests, exercise the complete command flow through `domain.process()`:

```python
domain.process(
    PlaceOrder(buyer_id="user-1", items=[{"product_id": "p1", "qty": 2}]),
    asynchronous=False,
)

repo = domain.repository_for(Order)
order = repo.get(order_id)
assert order.status == "PLACED"
```
