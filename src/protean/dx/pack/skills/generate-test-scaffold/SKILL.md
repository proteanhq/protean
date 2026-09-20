---
name: generate-test-scaffold
description: Generate test scaffolds from Protean domain definitions. Analyzes existing aggregates, commands, events, handlers, value objects, and entities to produce focused pytest test stubs for user-written business logic - aggregate behavior, state transitions, invariants, event raising, handler orchestration, and end-to-end flows. Follows Protean's testing pyramid (domain unit tests as majority). Does NOT generate tests for framework-guaranteed behavior (VO immutability, field validation, registration). Use when the user asks to "generate tests", "scaffold tests", "create test stubs", "add tests for my domain", "write tests for aggregate", "generate test file", "add test coverage", or when they have domain code that needs test coverage.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: []
---

# Generate Test Scaffold

Generate comprehensive pytest tests for existing Protean domain definitions, focusing on **user-written business logic**.

## The testing pyramid

```
                /\
               /  \
              / E2E \        Few: Full flows with persistence
             /--------\
            /Integration\    Some: Handler + repo + domain
           /--------------\
          /  Domain Unit    \ Many: Aggregates, VOs, services
         /____________________\
```

Domain unit tests are the **majority** of your test suite — they test the most important code (business rules) with the least overhead (no infrastructure).

## What to test vs. what to skip

### Test (user-written business logic)

1. **Aggregate factory methods** — correct state after creation, correct events raised via `raise_()`
2. **Aggregate state-change methods** — before/after state assertions, status transitions
3. **User-defined invariants** — `@invariant.pre` and `@invariant.post` enforcement
4. **Business rules** — methods that reject invalid operations (e.g., "can't cancel a draft order")
5. **Event data correctness** — events raised by `raise_()` carry the right field values
6. **Value object custom operations** — user-defined methods like `Money.add()`, not VO construction/equality
7. **Entity management** — add/remove entities through aggregate methods
8. **Handler orchestration** — `domain.process()` creates/updates the right aggregate state
9. **Event handler side effects** — cross-aggregate state changes triggered by events
10. **End-to-end flows** — full lifecycle from command to final state

### Skip (framework guarantees)

- VO construction, equality, immutability — guaranteed by `@domain.value_object`
- Command/event immutability — guaranteed by decorators
- Field-level validation (`required`, `max_length`, `min_value`, `choices`) — Protean Layer 1
- Element registration in `domain.registry` — guaranteed if decorator is used
- `meta_.part_of` associations, `meta_.stream_category` — framework wiring
- Command `.payload` dict access — framework feature

### Avoid mocks — use real domain elements

Protean's in-memory infrastructure (repositories, event processing with `"sync"` mode) makes mocks unnecessary in almost all cases. Construct real aggregates, value objects, entities, commands, and events directly in tests. Use `domain.process()` and `domain.repository_for()` for integration tests. Mocks should only be used when testing interactions with truly external systems (e.g., third-party HTTP APIs) that cannot be replaced by Protean's built-in test infrastructure.

## Information to gather

Before generating tests, identify:

- [ ] Aggregate factory methods (classmethods that create instances)
- [ ] Aggregate state-change methods (instance methods that mutate state)
- [ ] Events raised by each method via `raise_()`
- [ ] User-defined invariants (`@invariant.pre`, `@invariant.post`)
- [ ] Business rules (conditionals that raise `ValueError` or `ValidationError`)
- [ ] Command handlers and what commands they handle
- [ ] Event handlers and what events they react to
- [ ] Value object custom operations (user-defined methods)
- [ ] Cross-aggregate relationships (event handlers listening to other streams)

## Process

### Step 1: Analyze domain definitions

Read the user's domain code and catalog:
- Every aggregate class + its methods
- Every event class + which methods raise it
- Every command + handler pair
- Every event handler + what side effects it produces
- Every invariant + what condition it guards

### Step 2: Generate aggregate unit tests

For each aggregate method, generate tests for:

```python
class TestOrderBehavior:
    def test_place_sets_status_to_placed(self):
        """place() transitions status from draft to placed."""
        order = Order.create(customer_id="cust-1")
        order.add_item(product_id="p-1", quantity=2, unit_price=10.0)
        order.place()
        assert order.status == "placed"

    def test_place_raises_order_placed_event(self):
        """place() raises OrderPlaced with correct data."""
        order = Order.create(customer_id="cust-1")
        order.add_item(product_id="p-1", quantity=2, unit_price=10.0)
        order.place()
        assert len(order._events) == 1
        event = order._events[0]
        assert isinstance(event, OrderPlaced)
        assert event.order_id == order.id

    def test_place_fails_for_non_draft_order(self):
        """place() rejects orders not in draft status."""
        order = Order.create(customer_id="cust-1")
        order.add_item(product_id="p-1", quantity=1, unit_price=5.0)
        order.place()
        with pytest.raises(ValueError):
            order.place()  # Already placed
```

**Pattern**: Use `_events.clear()` to isolate event assertions when testing a method after a factory that also raises events.

### Step 3: Generate invariant tests

```python
class TestOrderInvariants:
    def test_cannot_place_empty_order(self):
        """Invariant: placed orders must have items."""
        order = Order.create(customer_id="cust-1")
        with pytest.raises(ValidationError):
            order.place()  # No items added
```

### Step 4: Generate handler orchestration tests

```python
class TestHandlerProcessing:
    def test_register_user_creates_and_persists(self):
        """domain.process(RegisterUser) creates a registered User."""
        result = domain.process(
            RegisterUser(email="a@test.com", name="Alice"),
            asynchronous=False,
        )
        user = domain.repository_for(User).get(result)
        assert user.status == "registered"
        assert user.email == "a@test.com"
```

### Step 5: Generate event handler side-effect tests

```python
class TestCrossAggregateFlow:
    def test_order_placed_reserves_inventory(self):
        """OrderPlaced event triggers stock reservation."""
        inventory = Inventory(product_id="p-1", available=100, reserved=0)
        domain.repository_for(Inventory).add(inventory)

        order = Order.place(customer_id="c-1", product_id="p-1", quantity=5)
        domain.repository_for(Order).add(order)

        updated = domain.repository_for(Inventory).get(inventory.id)
        assert updated.available == 95
        assert updated.reserved == 5
```

### Step 6: Generate end-to-end lifecycle tests

Test full sequences: create → modify → verify final state + side effects.

### Step 7: Set up test infrastructure

```python
import pytest
from protean.exceptions import ValidationError
from your_module import Order, OrderPlaced, domain  # type: ignore

# The root conftest.py auto-initializes domain and provides domain_context
# No manual setup needed in test files
```

## Test class organization

| Test class name | What it covers |
|----------------|---------------|
| `Test{Aggregate}Behavior` | Factory methods, state transitions, entity management |
| `Test{Aggregate}BusinessRules` | Invariants, rejected operations, error cases |
| `Test{Aggregate}Events` | Events raised with correct data |
| `TestHandlerProcessing` | domain.process() flows, persistence verification |
| `TestCrossAggregateFlow` | Event handler side effects across aggregates |
| `TestLifecycle` | Full end-to-end sequences |

## Key assertion patterns

```python
# State after method call
assert order.status == "placed"

# Events raised
assert len(order._events) == 1
assert isinstance(order._events[0], OrderPlaced)

# Event data
event = order._events[0]
assert event.order_id == order.id

# Clear events to isolate subsequent method
order._events.clear()

# Business rule rejection
with pytest.raises(ValueError):
    order.cancel("reason")

# Invariant rejection
with pytest.raises(ValidationError):
    order.place()

# Handler persistence
result = domain.process(cmd, asynchronous=False)
entity = domain.repository_for(Aggregate).get(result)

# Cross-aggregate side effect
domain.repository_for(Source).add(source)
target = domain.repository_for(Target).get(target_id)
assert target.field == expected
```

## Common mistakes

1. **Testing framework guarantees** — Don't test VO immutability, command required fields, or registry presence. Protean handles these.
2. **Forgetting `_events.clear()`** — After a factory that raises events, clear `_events` before testing the next method's events.
3. **Missing `asynchronous=False`** — Always pass `asynchronous=False` to `domain.process()` in tests for synchronous execution.
4. **Not creating prerequisite state** — For event handler tests, ensure the target aggregate exists in the repository before the source event fires.
5. **Using mocks instead of real domain elements** — Protean provides in-memory repositories and synchronous event processing for tests. Construct real aggregates, VOs, commands, and events instead of mocking them. Mocks hide bugs and make tests brittle. Reserve mocks only for truly external dependencies (third-party APIs) that have no in-memory substitute.

## Complete examples

- [Aggregate unit tests](assets/scaffold_aggregate_unit.py) — Order with entities, value objects, invariants
- [Command flow tests](assets/scaffold_command_flow.py) — User registration with handler and API
- [Event-driven flow tests](assets/scaffold_event_driven_flow.py) — Cross-aggregate Order → Inventory sync

## Detailed references

- [Aggregate test patterns](references/aggregate-tests.md) — Factory methods, state transitions, invariants, entity management
- [Handler test patterns](references/handler-tests.md) — Command/event handler orchestration, API endpoints
- [Integration test patterns](references/integration-tests.md) — Cross-aggregate flows, lifecycle tests

## Related skills

- [aggregate](../aggregate/SKILL.md) — Aggregate definition patterns
- [command](../command/SKILL.md) — Command definition
- [event](../event/SKILL.md) — Event definition
- [command-handler](../command-handler/SKILL.md) — Handler patterns
- [event-handler](../event-handler/SKILL.md) — Event handler patterns
- [value-object](../value-object/SKILL.md) — Value object patterns
- [add-use-case](../add-use-case/SKILL.md) — Vertical slice patterns

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
