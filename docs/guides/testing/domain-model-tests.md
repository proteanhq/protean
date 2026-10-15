# Domain Model Tests

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Domain model tests are **unit tests** that validate your aggregates, entities,
value objects, invariants, and domain services. They are the foundation of your
test suite, fast, isolated, and focused on business rules.

These tests require no infrastructure and run entirely in-memory, making them
the fastest tests in your suite. Every business rule you encode in your domain
model should have a corresponding test.

!!!note "Don't Test What Protean Guarantees"
    Protean already guarantees that fields work correctly, `required=True` raises
    validation errors, `max_length` is enforced, `default` values are applied, value objects
    are immutable and compared by value, and events are dispatched in order.
    You do not need to write tests for these behaviors. Focus your tests on
    logic **you** wrote: custom methods, state transitions, invariants, and
    domain rules.

## Test Setup

Domain model tests use Protean's `DomainFixture` to initialize the domain
with in-memory adapters (the default) and manage per-test cleanup. Set
processing to `"sync"` so that events and commands are handled immediately
within tests. In your project these fixtures go in `tests/conftest.py`, and they import
`domain` from your application's package (`bookstore` here):

```python
# fragment
--8<-- "guides/testing/domain-model-tests/conftest.py:conftest"
```

The tests on this page exercise this domain:

??? example "The domain under test"

    ```python
    # fragment
    --8<-- "guides/testing/domain-model-tests/bookstore/__init__.py:domain"
    ```

`DomainFixture.setup()` calls `domain.init()` to discover and wire all
decorated domain elements, and creates database schema if needed.
`domain_context()` activates the domain for each test and resets all
data (providers, brokers, event store) on exit.

!!!note
    You do not need Docker, databases, or message brokers for domain model
    tests. Protean's in-memory adapters are used by default.

## Testing Aggregates

Aggregates are the core of your domain model. Test that your custom methods
correctly transition state and raise events.

### State Transitions

Test that aggregate methods correctly mutate state. These are methods **you**
wrote, your business logic:

```python
# fragment
--8<-- "guides/testing/domain-model-tests/001.py:state_transition"
```

### Event Raising

Verify that your aggregate methods raise the expected domain events:

```python
# fragment
--8<-- "guides/testing/domain-model-tests/001.py:event_raising"
```

## Testing Entities

Entities live within aggregates and have their own identity. Test the business
logic in entity methods, especially when they affect the parent aggregate's
state:

```python
# fragment
--8<-- "guides/testing/domain-model-tests/001.py:entity"
```

## Testing Value Objects

Protean guarantees that value objects are immutable and compared by value. You
do not need to test these properties. Instead, test any **custom logic** you
define on your value objects:

```python
# fragment
--8<-- "guides/testing/domain-model-tests/001.py:value_object"
```

## Testing Invariants

Invariants are **your** business rules. They represent domain constraints that
you define. Protean guarantees that invariants are *enforced* (triggered on
initialization and mutation), but you should test that **your invariant logic
is correct** and catches the violations you intend.

### Testing That Invalid State Is Rejected

```python
# fragment
--8<-- "guides/testing/domain-model-tests/001.py:invalid_state"
```

### Testing That Valid State Is Accepted

Don't just test the negative case, verify that correctly constructed aggregates
pass your invariant:

```python
# fragment
--8<-- "guides/testing/domain-model-tests/001.py:valid_state"
```

### Pre-Invariants

Pre-invariants validate state *before* a mutation occurs. They are useful for
guard conditions, test that your guard logic correctly rejects invalid
operations:

```python
# fragment
--8<-- "guides/testing/domain-model-tests/001.py:pre_invariant"
```

## Testing Domain Services

Domain services hold business rules that span multiple aggregates. Test them
by passing in the aggregates and checking the outcome.

```python
# fragment
--8<-- "guides/testing/domain-model-tests/001.py:domain_service"
```

The service confirms the order and leaves the inventory as it was. The
example does not reserve stock. If your domain reserves it in a later step,
test that step on its own.

### Domain Service Invariants

Domain services can also have pre-invariants. Test that they reject invalid
input:

```python
# fragment
--8<-- "guides/testing/domain-model-tests/001.py:domain_service_invariant"
```

## Organizing Domain Model Tests

A recommended directory structure:

```
tests/
├── conftest.py              # Domain fixture
├── test_book.py             # Aggregate tests
├── test_order.py            # Aggregate + entity tests
├── test_money.py            # Value object tests
├── test_fulfillment.py      # Domain service tests
└── ...
```

Group tests by the aggregate or concept they exercise. Each test file imports
the elements it needs from your application code.
