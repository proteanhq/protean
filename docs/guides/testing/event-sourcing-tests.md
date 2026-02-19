# Event Sourcing Tests

!!! abstract "Applies to: Event Sourcing"


Protean provides a fluent test DSL for event-sourced aggregates through the
`protean.testing` module. It lets you write integration tests that exercise
the full command processing pipeline — command handler, aggregate method,
repository, unit of work, and event store — in three words:

```python
from protean.testing import given

order = given(Order, order_created, order_confirmed).process(initiate_payment)
```

*"Given an Order after order_created and order_confirmed, process
initiate_payment."*

## Key Facts

- Tests exercise the **real pipeline** — `domain.process()` is called, not a
  mock. Commands go through command handlers, repository loading, aggregate
  methods, and event store writes.
- The DSL uses **plain Python** for assertions — `in`, `[]`, `len`, `assert`.
  No custom assertion methods.
- Attribute access is **proxied** to the aggregate — `order.status` works
  directly on the result object.
- Designed for event-sourced aggregates (`is_event_sourced=True`). For
  non-event-sourced aggregates, see
  [Application Tests](./application-tests.md).

## The Three Words

### `given(AggregateCls, *events)`

Entry point. Pass the aggregate class and zero or more past domain events
that constitute the aggregate's history:

```python
given(Order)                                    # no history (create command)
given(Order, order_created)                     # one history event
given(Order, order_created, order_confirmed)    # multiple history events
```

### `.after(*events)`

Accumulate more history events. Maps to BDD "And given" steps. Returns self
for chaining:

```python
given(Order, order_created).after(order_confirmed).after(payment_initiated)
```

### `.process(command)`

Dispatch a command through the domain's full processing pipeline. Seeds the
event store with given events, then calls `domain.process(command)`. Returns
self:

```python
order = given(Order, order_created, order_confirmed).process(initiate_payment)
```

## Asserting Outcomes

After `.process()`, the result object provides:

### Aggregate State

Attribute access is proxied to the underlying aggregate:

```python
assert order.status == "PAYMENT_PENDING"
assert order.customer == "Alice"
assert order.pricing.grand_total == 99.99  # deep access works
```

### Accepted or Rejected

```python
assert order.accepted          # command processed without exception
assert order.rejected          # command raised an exception
assert order.rejection is None # the exception object, or None
```

### Events (EventLog)

New events raised by the command are available via `.events`. The `EventLog`
class uses Python's own vocabulary:

```python
# Presence check
assert PaymentPending in order.events

# Access by type (first match; raises KeyError if missing)
assert order.events[PaymentPending].payment_id == "pay-001"

# Safe access (returns None if missing)
assert order.events.get(PaymentFailed) is None

# Ordered type list
assert order.events.types == [PaymentPending]

# Count
assert len(order.events) == 1

# All events of a type
assert len(order.events.of_type(ItemAdded)) == 3

# Iteration
for event in order.events:
    print(event)

# Access by index
assert order.events[0].payment_id == "pay-001"
```

### Raw Aggregate

If you need the aggregate instance directly:

```python
assert isinstance(order.aggregate, Order)
```

## Complete Examples

### Testing a Create Command

When testing a command that creates a new aggregate, use `given()` with no
history events. The command handler must return the aggregate identifier so
that the DSL can locate the aggregate in the event store:

```python
from protean.testing import given


def test_create_order(test_domain):
    order = given(Order).process(
        CreateOrder(order_id="ord-1", customer="Alice", amount=99.99)
    )

    assert order.accepted
    assert OrderCreated in order.events
    assert order.status == "CREATED"
    assert order.customer == "Alice"
```

### Testing a Command with History

Seed the aggregate's history and then process a command that depends on
that state:

```python
def test_confirm_order(order_created):
    order = given(Order, order_created).process(
        ConfirmOrder(order_id=order_created.order_id)
    )

    assert order.accepted
    assert OrderConfirmed in order.events
    assert order.status == "CONFIRMED"
```

### Testing Command Rejection

When a command violates a business rule, the exception is captured and the
aggregate reflects the pre-command state:

```python
def test_cannot_pay_unconfirmed_order(order_created, initiate_payment):
    order = given(Order, order_created).process(initiate_payment)

    assert order.rejected
    assert isinstance(order.rejection, ValidationError)
    assert "must be confirmed" in str(order.rejection)
    assert len(order.events) == 0
    assert order.status == "CREATED"  # unchanged
```

### Testing with Multiple History Events

Use `.after()` or pass multiple events to `given()`:

```python
def test_payment_on_confirmed_order(
    order_created, order_confirmed, initiate_payment
):
    order = (
        given(Order, order_created)
        .after(order_confirmed)
        .process(initiate_payment)
    )

    assert order.accepted
    assert PaymentPending in order.events
    assert order.events[PaymentPending].payment_id == "pay-001"
```

### Testing Event Attributes

Access event fields through the `EventLog`:

```python
def test_payment_event_carries_payment_id(order_created, order_confirmed):
    order = given(Order, order_created, order_confirmed).process(
        InitiatePayment(order_id=order_created.order_id, payment_id="pay-42")
    )

    event = order.events[PaymentPending]
    assert event.payment_id == "pay-42"
    assert event.order_id == order_created.order_id
```

## Test Setup

### conftest.py for Event-Sourced Tests

Event-sourced tests use the same `DomainFixture` setup as other Protean
tests. The domain must have `event_processing` and `command_processing`
set to `"sync"`:

```python
# tests/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield
```

### Event Fixtures

Define reusable event fixtures for your aggregate's history:

```python
# tests/conftest.py (or tests/ordering/conftest.py)
from uuid import uuid4

from myapp.events import OrderCreated, OrderConfirmed
from myapp.commands import InitiatePayment


@pytest.fixture
def order_id():
    return str(uuid4())


@pytest.fixture
def order_created(order_id):
    return OrderCreated(
        order_id=order_id, customer="Alice", amount=99.99
    )


@pytest.fixture
def order_confirmed(order_id):
    return OrderConfirmed(order_id=order_id)


@pytest.fixture
def initiate_payment(order_id):
    return InitiatePayment(
        order_id=order_id, payment_id="pay-001"
    )
```

## Design Notes

### Why Integration Tests, Not Unit Tests

`.process(command)` calls `domain.process()` — the same entry point as
production code. Nothing is mocked. This gives you confidence that the
full pipeline works correctly: command handler routing, aggregate loading
from the event store, business method execution, event raising, and
persistence.

### Why `__getattr__` Proxy

`order.status` works because `AggregateResult.__getattr__` delegates to
the underlying aggregate. This keeps tests reading like domain language
rather than test infrastructure.

### Why EventLog Uses Python Operators

`in` for presence, `[]` for access, `len` for count, `for` for iteration.
No `.has_event()`, no `.event_count()`, no custom assertion methods. Python's
built-in operators carry the meaning.

### Location at `protean.testing`

Following the convention of `django.test`, `flask.testing`, and
`unittest.mock` — a top-level testing module for test utilities. Separate
from the pytest plugin in `protean.integrations.pytest`, which handles
fixture lifecycle (`DomainFixture`), not domain-level test DSL.

## API Reference

### `given(aggregate_cls, *events) -> AggregateResult`

Start an event-sourcing test sentence.

### `AggregateResult`

| Property/Method | Description |
|-----------------|-------------|
| `.after(*events)` | Accumulate more history events. Returns self. |
| `.process(command)` | Dispatch command through `domain.process()`. Returns self. |
| `.events` | `EventLog` of new events raised by the command. |
| `.rejection` | The exception if rejected, or `None`. |
| `.accepted` | `True` if the command succeeded. |
| `.rejected` | `True` if the command raised an exception. |
| `.aggregate` | The raw aggregate instance. |
| `.<attr>` | Proxied to the underlying aggregate. |

### `EventLog`

| Operation | Description |
|-----------|-------------|
| `EventCls in log` | Check if an event of this type exists. |
| `log[EventCls]` | First event of type (raises `KeyError` if missing). |
| `log[index]` | Event by position. |
| `log.get(EventCls)` | Safe access — returns `None` if not found. |
| `log.of_type(EventCls)` | All events of the given type. |
| `log.types` | Ordered list of event classes. |
| `len(log)` | Number of events. |
| `for e in log` | Iterate over events. |
