# Event Sourcing Tests

<span class="pathway-tag pathway-tag-es">ES</span>

Protean provides a fluent test DSL for event-sourced aggregates through the
`protean.testing` module. It lets you write integration tests that exercise the
full command processing pipeline (command handler, aggregate method,
repository, unit of work, and event store) in three words:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:three_words"
```

*"Given an Order after order_created and order_confirmed, process
initiate_payment."*

Every `.process()` call runs through the real pipeline (command handler,
aggregate loading, event store writes) with no mocks. For testing
non-event-sourced aggregates, see [Application Tests](./application-tests.md).

The examples on this page test this event-sourced `Order`:

??? example "The domain under test"

    ```python
    --8<-- "guides/testing/event-sourcing-tests/001.py:domain"
    ```

## The Three Words

### `given(AggregateCls, *events)`

Entry point. Pass the aggregate class and zero or more past domain events
that constitute the aggregate's history:

```python
# fragment
given(Order)                                    # no history (create command)
given(Order, order_created)                     # one history event
given(Order, order_created, order_confirmed)    # multiple history events
```

### `.after(*events)`

Accumulate more history events. Maps to BDD "And given" steps. Returns self
for chaining:

```python
# fragment
given(Order, order_created).after(order_confirmed).after(payment_initiated)
```

### `.process(command)`

Dispatch a command through the domain's full processing pipeline. Seeds the
event store with given events, then calls `domain.process(command)`. Returns
self:

```python
# fragment
order = given(Order, order_created, order_confirmed).process(initiate_payment)
```

## Multi-Command Chaining

Call `.process()` multiple times to build up aggregate state through the real
pipeline, no hand-crafted event fixtures needed:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:chaining"
```

Each `.process()` runs the command through the real pipeline. The event store
accumulates naturally, just like production.

After chaining:

- `.events` contains events from the **last** `.process()` call only.
- `.all_events` contains events from **all** `.process()` calls.
- `.accepted` / `.rejected` reflects the **last** `.process()` call.

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:events_vs_all_events"
```

### When to Use Which Pattern

| Pattern | Use when |
|---------|----------|
| `given(Order, e1, e2).process(cmd)` | You need precise control over history, specific event field values, edge-case states, or states that can't easily be reached through commands. |
| `given(Order).process(cmd1).process(cmd2)` | You're testing a lifecycle or user journey. The setup steps aren't the focus; the final command is. |
| `Order.from_events([e1, e2])` | Unit testing aggregate logic directly, without the command pipeline. |

Both patterns coexist. Event-based `given()` gives surgical precision.
Command chaining gives lifecycle-level testing.

## Asserting Outcomes

After `.process()`, the result object provides:

### Aggregate State

Attribute access is proxied to the underlying aggregate:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:aggregate_state"
```

### Accepted or Rejected

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:accepted_or_rejected"
```

### Rejection Messages

For cleaner error assertions, use `.rejection_messages`, a flat list of error strings extracted
from the exception:

```python
# fragment
assert order.rejected
assert "Order must be confirmed before payment" in order.rejection_messages
```

This works with `ValidationError` (flattens the `messages` dict) and other
exception types (wraps as `[str(exc)]`). Returns `[]` when the command
was accepted.

### Events (EventLog)

New events raised by the command are available via `.events`. The `EventLog`
class uses Python's own vocabulary:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:event_log"
```

### Raw Aggregate

If you need the aggregate instance directly:

```python
# fragment
assert isinstance(order.aggregate, Order)
```

## Complete Examples

### Testing a Create Command

When testing a command that creates a new aggregate, use `given()` with no
history events. The command handler must return the aggregate identifier so
that the DSL can locate the aggregate in the event store:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:create_command"
```

### Testing a Command with History

Seed the aggregate's history and then process a command that depends on
that state:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:command_with_history"
```

### Testing Command Rejection

When a command violates a business rule, the exception is captured and the
aggregate reflects the pre-command state:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:rejection"
```

### Testing with Multiple History Events

Use `.after()` or pass multiple events to `given()`:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:multiple_history"
```

### Testing Event Attributes

Access event fields through the `EventLog`:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:event_attributes"
```

### Testing a Full Lifecycle

Use multi-command chaining to test a complete user journey:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:lifecycle"
```

### Testing Rejection Mid-Chain

When a chained command fails, the aggregate reflects the state from
prior successful commands:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:rejection_mid_chain"
```

## Test Setup

### conftest.py for Event-Sourced Tests

Event-sourced tests use the same `DomainFixture` setup as other Protean
tests. The domain must have `event_processing` and `command_processing`
set to `"sync"`. In your project these fixtures go in `tests/conftest.py`,
and `domain` is your application's domain (`from myapp import domain`):

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:conftest"
```

### Event Fixtures

Define reusable event fixtures for your aggregate's history:

```python
--8<-- "guides/testing/event-sourcing-tests/001.py:event_fixtures"
```

## Design Notes

### Why Integration Tests, Not Unit Tests

`.process(command)` calls `domain.process()`. The same entry point as
production code. Nothing is mocked. This gives you confidence that the full
pipeline works correctly: command handler routing, aggregate loading from the
event store, business method execution, event raising, and persistence.

### Why `__getattr__` Proxy

`order.status` works because `AggregateResult.__getattr__` delegates to
the underlying aggregate. This keeps tests reading like domain language
rather than test infrastructure.

### Why EventLog Uses Python Operators

`in` for presence, `[]` for access, `len` for count, `bool` for truthiness,
`for` for iteration. No `.has_event()`, no `.event_count()`, no custom
assertion methods. Python's built-in operators carry the meaning.

### Why Multi-Command Chaining

Event-based `given(Order, e1, e2)` requires hand-crafting events that
encode knowledge of the aggregate's internal event structure. If the
aggregate changes which events a command produces, all fixtures break.

Multi-command chaining uses the real pipeline to build up state, so tests
describe the user journey in terms of commands (the public API). If
aggregate internals change, chained tests survive untouched.

### Location at `protean.testing`

Following the convention of `django.test`, `flask.testing`, and
`unittest.mock`, a top-level testing module for test utilities. Separate from
the pytest plugin in `protean.integrations.pytest`, which handles fixture
lifecycle (`DomainFixture`), not domain-level test DSL.

## API Reference

### `given(aggregate_cls, *events) -> AggregateResult`

Start an event-sourcing test sentence.

### `AggregateResult`

| Property/Method | Description |
|-----------------|-------------|
| `.after(*events)` | Accumulate more history events. Returns self. |
| `.process(command)` | Dispatch command through `domain.process()`. Can be called multiple times. Returns self. |
| `.events` | `EventLog` of new events raised by the last command. |
| `.all_events` | `EventLog` of all events raised across all `.process()` calls. |
| `.rejection` | The exception if rejected, or `None`. |
| `.accepted` | `True` if the last command succeeded. |
| `.rejected` | `True` if the last command raised an exception. |
| `.rejection_messages` | Flat list of error strings from the rejection, or `[]`. |
| `.aggregate` | The raw aggregate instance. |
| `.<attr>` | Proxied to the underlying aggregate. |

### `EventLog`

| Operation | Description |
|-----------|-------------|
| `EventCls in log` | Check if an event of this type exists. |
| `log[EventCls]` | First event of type (raises `KeyError` if missing). |
| `log[index]` | Event by position. |
| `log.get(EventCls)` | Safe access, returns `None` if not found. |
| `log.of_type(EventCls)` | All events of the given type. |
| `log.types` | Ordered list of event classes. |
| `log.first` | First event, or `None` if empty. |
| `log.last` | Last event, or `None` if empty. |
| `len(log)` | Number of events. |
| `bool(log)` | `True` if non-empty, `False` if empty. |
| `for e in log` | Iterate over events. |
