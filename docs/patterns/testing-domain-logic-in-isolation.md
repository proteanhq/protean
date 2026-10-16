# Testing Domain Logic in Isolation

## The Problem

A developer writes tests for an order placement feature:

```python
# fragment
class TestPlaceOrder:

    def test_place_order(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(OrderCommandHandler, part_of=Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            command = PlaceOrder(
                order_id="ord-123",
                customer_id="cust-456",
                items=[{"product_id": "p-1", "quantity": 2, "unit_price": 10.0}],
                total=20.0,
            )
            test_domain.process(command)

            repo = test_domain.repository_for(Order)
            order = repo.get("ord-123")
            assert order.status == "placed"
            assert order.total == 20.0
```

This test works, but it tests the entire pipeline: command deserialization,
handler dispatch, repository operations, and aggregate behavior, all in one
test. When it fails, which part broke? The test doesn't tell you. It requires
registering multiple domain elements, initializing the domain, and managing a
domain context. It's slow relative to a unit test and tests more than it
intends to.

The deeper problem: when tests can only exercise business logic through the
handler pipeline, developers write fewer tests. The setup overhead discourages
testing edge cases, boundary conditions, and specific business rules. The
domain model (the most important part of the system) ends up being the least
tested.

---

## The Pattern

Test domain logic **directly on domain objects** (aggregates, value objects,
entities, and domain services) without handlers, repositories, commands, or
infrastructure. These are **unit tests** that exercise business rules in
isolation.

```
Integration test (whole pipeline):
  Command → Handler → Repository → Aggregate → Event → Database
  (tests the plumbing)

Unit test (domain in isolation):
  Aggregate → call method → assert state
  (tests the business logic)
```

Both types of tests are valuable. But domain unit tests should be the
**majority** of your test suite because they test the most important code
(business rules) with the least overhead (no infrastructure).

### Test Setup

The examples below assume a `tests/conftest.py` that uses Protean's
`DomainFixture` to initialize the domain and provide a per-test context. The
domain and its elements live in an `isolation_shop` package, and the tests
import them from `isolation_shop.domain`:

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/conftest.py:fixtures"
```

With this setup, every test runs within an active domain context and all
data is reset between tests automatically.

---

## Testing Aggregates

### Basic State Changes

Test aggregate methods by constructing an aggregate, calling a method, and
asserting the resulting state:

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_aggregates.py:placement"
```

No repository, no handler, no command. Just the aggregate and its behavior.

### Preconditions and Business Rules

Each business rule gets its own test:

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_aggregates.py:account_rules"
```

Five tests, each targeting a specific business rule. Each runs in
milliseconds. Together, they comprehensively test the withdrawal behavior.

### Domain Events

Verify that aggregate methods raise the correct events:

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_aggregates.py:events"
```

The `_events` list on the aggregate collects events raised via `raise_()`.
This allows direct inspection without infrastructure.

---

## Testing Value Objects

### Construction and Validation

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_value_objects.py:construction"
```

### Equality

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_value_objects.py:equality"
```

### Operations

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_value_objects.py:operations"
```

### Immutability

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_value_objects.py:immutability"
```

---

## Testing Invariants

### Post-Invariants

Protean runs post-invariants when an aggregate is created and after every
change to it. When a change breaks one, Protean undoes the change:

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_invariants.py:post"
```

### Pre-Invariants

Protean runs pre-invariants before every change, against the state the
aggregate is in at that moment. Here a closed account rejects any change:

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_invariants.py:pre"
```

---

## Testing Domain Services

Domain services coordinate logic across aggregates. Test them by building the
service with aggregate instances directly:

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_domain_services.py:services"
```

No repositories, no handlers. Construct the aggregates, pass them to the
service, assert results.

---

## Testing Entities Within Aggregates

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_entities.py:entities"
```

Entities are tested through their parent aggregate, which is how they're
accessed in production.

---

## When Integration Tests Are Needed

Domain unit tests don't replace integration tests. They complement them.
Integration tests verify that the pipeline works end-to-end. They use the
domain that `conftest.py` already initialized, with its repositories and
handlers, so they need no setup of their own:

### Repository Integration

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_integration.py:persistence"
```

### Handler Pipeline

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_integration.py:handler"
```

### Event Handler Integration

```python
# fragment
--8<-- "patterns/testing-domain-logic-in-isolation/test_integration.py:event_handler"
```

---

## The Testing Pyramid

```
                    /\
                   /  \
                  / E2E \        Few: Full system with real databases
                 /--------\
                /Integration\    Some: Handler + repo + domain
               /--------------\
              /  Domain Unit    \ Many: Aggregates, VOs, services
             /____________________\
```

- **Domain unit tests (base):** Fast, focused, comprehensive. Test every
  business rule, every edge case, every state transition. These are your
  primary tests.

- **Integration tests (middle):** Verify that the pipeline works. Test that
  commands flow through handlers, aggregates are persisted correctly, and
  events are delivered to handlers.

- **End-to-end tests (top):** Verify the full system with real databases
  and brokers. Test critical paths only. These are slow and brittle.

The domain unit tests should be the **majority** of your test suite because
they test the most important code with the least overhead.

---

## Summary

| Test Type | What It Tests | Setup Needed | Speed | Coverage Goal |
|-----------|--------------|-------------|-------|---------------|
| Domain unit | Business rules, invariants, state changes | Just the aggregate | Very fast | Comprehensive |
| Value object | Concept rules, equality, operations | Just the VO | Very fast | All validations |
| Domain service | Cross-aggregate coordination | Aggregates (no repos) | Very fast | All paths |
| Integration | Handler + repo pipeline | Domain registration | Medium | Critical paths |
| End-to-end | Full system behavior | Real infrastructure | Slow | Happy paths |

Domain logic is the most important code in your system. Test it directly,
without infrastructure, in isolation. Construct aggregates, call methods,
assert results. Save integration tests for verifying the plumbing.

!!! tip "Run all test layers in both modes"
    Domain unit tests already use in-memory adapters. Integration tests can
    too, with Protean's [Dual-Mode Testing](dual-mode-testing.md), a single `pytest --protean-env memory`
    flag switches every adapter to its in-memory equivalent. Run fast during
    development, then validate against real infrastructure in CI.

---

!!! tip "Related reading"
    **Concepts:**

    - [Aggregates](../concepts/building-blocks/aggregates.md): Aggregate structure and invariants.
    - [Value Objects](../concepts/building-blocks/value-objects.md): Testing immutable domain concepts.

    **Guides:**

    - [Domain Model Tests](../guides/testing/domain-model-tests.md): Unit testing aggregates, entities, and value objects.
    - [Fixtures and Patterns](../guides/testing/fixtures-and-patterns.md): Reusable pytest fixtures and test recipes.
