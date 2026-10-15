# Test Event-Driven Flows End-to-End

## The Problem

Unit testing individual domain elements is straightforward. You construct an
aggregate, call a method, assert the resulting state. The [Testing Domain Logic
in Isolation](testing-domain-logic-in-isolation.md) pattern covers this well.
But real event-driven systems are not made of isolated pieces. They are made of
*chains*:

```
PlaceOrder (command)
  -> OrderCommandHandler (processes command)
    -> Order.place() (mutates aggregate, raises OrderPlaced)
      -> InventoryEventHandler (reserves stock, raises InventoryReserved)
        -> OrderDashboardProjector (updates read model)
```

Testing the full chain is harder. The command fires a handler, which persists
an aggregate, which raises an event, which triggers another handler, which
updates a projection. Each link depends on the previous one completing
correctly. Without guidance, teams fall into predictable traps:

**Trap 1: Skipping E2E tests entirely.** "Our unit tests pass, so the chain
works." It doesn't. A misconfigured stream category or missing handler
registration only shows up when the full chain runs.

**Trap 2: Testing handlers in isolation with fabricated events.** A developer
constructs an `OrderPlaced` event manually and calls the handler directly. The
handler works, but in production the event has different metadata or is routed
to a different stream.

**Trap 3: Fragile async test setups.** The team reaches for the Engine but
wrestles with timing:

```python
# fragment
# FRAGILE: How long do we sleep? Too short and the test is flaky.
# Too long and the suite is slow.
def test_order_flow(self):
    domain.process(PlaceOrder(...))
    time.sleep(2)  # Hope the engine processes everything...
    time.sleep(3)  # ...maybe add more time for slow CI...
    projection = domain.repository_for(OrderDashboard).get("ord-123")
    assert projection.status == "placed"  # Fails intermittently
```

The result: teams either avoid testing event chains entirely or build
unreliable tests that erode trust in the suite.

---

## The Pattern

Test event-driven flows at three levels. Each level trades speed for
realism. Most teams need all three, but the middle level covers the
majority of integration needs.

### Level 1: Domain unit tests

Test aggregates, value objects, and domain services directly. No handlers,
no repositories, no event processing infrastructure.

```
Aggregate -> call method -> assert state + assert _events
```

This is the [Testing Domain Logic in Isolation](testing-domain-logic-in-isolation.md)
pattern. It verifies that business logic produces the correct state and raises
the correct events. It does **not** verify that events reach their handlers or
that projections update.

**Use for:** Business rules, invariants, state transitions, event payloads.

### Level 2: Sync flow tests

Set `event_processing = "sync"` in the domain configuration. With sync
processing, event handlers and projectors fire **inline** during the Unit of
Work commit, in the same thread, in the same process, with no async machinery.

```
domain.process(command)
  -> handler fires synchronously
    -> aggregate persisted
      -> events dispatched inline
        -> event handlers fire inline
          -> projections updated
```

After `domain.process()` returns, the full chain has already executed. You can
assert on projection state immediately:

```python
# fragment
domain.process(PlaceOrder(...))

# No sleep, no engine, no async -- everything already ran
view = domain.view_for(OrderDashboard)
dashboard = view.get("ord-123")
assert dashboard.status == "placed"
```

**Use for:** Verifying the full command-to-projection chain, handler wiring,
event routing, projection correctness. This is your primary integration
testing tool.

### Level 3: Async E2E tests

Use `Engine(domain, test_mode=True)` for tests that exercise the actual
async processing infrastructure. The engine's `run()` method in test mode
starts every subscription, lets them process messages until none of them finds
more work, then performs a graceful shutdown. Messages that handlers raise
along the way are processed too. No `time.sleep()` guesswork.

Test mode stops waiting after about a second if some subscription keeps
finding work, for example while it retries a failing handler. A partitioned
stream subscription cannot report that it is idle, so with one present test
mode always waits the full second.

Test mode does not wait for a broker to redeliver a failed message. A broker
subscription waits `retry_delay_seconds` before it nacks the message, and the
inline broker then holds it back for its own `retry_delay`. Test mode stops
before the redelivery. To test a handler that fails and then succeeds on retry, set
both delays to 0:

```toml
[server.broker_subscription]
retry_delay_seconds = 0

[brokers.default]
provider = "inline"
retry_delay = 0
```

```python
# fragment
engine = Engine(domain, test_mode=True)
engine.run()

# Engine has processed all pending messages
view = domain.view_for(OrderDashboard)
dashboard = view.get("ord-123")
assert dashboard.status == "placed"
```

**Use for:** Subscription configuration, priority lane routing, error handling
paths (`handle_error` overrides), broker integration, outbox processing. Reserve
Level 3 for tests that **cannot** be verified with sync processing.

### When to use which level

| Concern | Level 1 | Level 2 | Level 3 |
|---------|---------|---------|---------|
| Business logic correctness | Yes | —  | —  |
| Event payloads and structure | Yes | —  | —  |
| Command-to-handler wiring | —  | Yes | —  |
| Event-to-handler routing | —  | Yes | —  |
| Projection updates | —  | Yes | —  |
| Multi-step event chains | —  | Yes | Yes |
| Subscription configuration | —  | —  | Yes |
| Priority lane routing | —  | —  | Yes |
| Error handling paths | —  | —  | Yes |
| Outbox processing | —  | —  | Yes |

Level 2 covers most integration needs. It runs at unit-test speed because
there is no event loop, no network, and no async coordination. Reserve Level 3
for the small number of tests that truly need the async Engine.

---

## Applying the Pattern

The examples below use a consistent e-commerce domain: an `Order` aggregate
that raises `OrderPlaced`, an `InventoryEventHandler` that reserves stock, and
an `OrderDashboard` projection that tracks order status.

### Domain setup

The domain lives in `ecommerce/domain.py`. `InventoryEventHandler` belongs to
`Inventory` but listens to the order stream, so it names that stream with
`stream_category`. Without it, the handler would listen to the inventory stream
and never receive `OrderPlaced`.

```python
--8<-- "patterns/testing-event-driven-flows/ecommerce/domain.py:domain"
```

### Test fixtures

A `tests/conftest.py` that initializes the domain with sync processing and
provides a per-test context. `DomainFixture` resets the data after each test:

```python
# fragment
--8<-- "patterns/testing-event-driven-flows/conftest.py:fixtures"
```

### Level 1: Domain unit tests

Test the aggregate's business logic and event raising directly:

```python
# fragment
--8<-- "patterns/testing-event-driven-flows/test_order_placement.py:level1"
```

These tests run in microseconds. They verify that `Order.place()` produces
the correct state and the correct event payload.

### Level 2: Sync flow tests

Test the full command-to-projection chain with sync processing:

```python
# fragment
--8<-- "patterns/testing-event-driven-flows/test_order_flow_sync.py:level2"
```

These tests verify the **wiring**: commands reach handlers, events reach
projectors, and projections reflect the correct state. They run at near
unit-test speed because sync processing has no async overhead.

### Level 3: Async E2E tests

Test the async engine for scenarios that require the full infrastructure. The
`async_events` fixture switches event processing to async for one test and
back to sync afterwards:

```python
# fragment
--8<-- "patterns/testing-event-driven-flows/test_order_flow_async.py:level3"
```

### Testing error handling paths

Level 3 is essential for testing `handle_error()` overrides. Put a handler
that fails on purpose in its own test module, so the other tests do not
register it:

```python
# fragment
--8<-- "patterns/testing-event-driven-flows/test_error_handling.py:errors"
```

### Testing priority lane routing

Priority lanes route events through the outbox to broker streams, so the
`priority_lanes` fixture switches the server to stream subscriptions and turns
lanes on. The test processes the command with `Priority.LOW` and checks that
the event went to the backfill stream and not the primary one:

```python
# fragment
--8<-- "patterns/testing-event-driven-flows/test_order_flow_async.py:priority"
```

---

## Anti-Patterns

### Using `time.sleep()` for synchronization

```python
# fragment
# WRONG: Arbitrary sleep durations are fragile.
def test_order_flow(self):
    domain.process(PlaceOrder(...))
    time.sleep(5)  # "Works on my machine" -- fails in CI
    dashboard = domain.repository_for(OrderDashboard).get("ord-123")
    assert dashboard.status == "placed"
```

**Why it's wrong:** The sleep duration is a guess. Too short and tests are
flaky. Too long and the suite is slow.

**Fix:** Use Level 2 (sync processing) or Level 3 (`Engine(test_mode=True)`)
for deterministic execution.

### Testing handlers without the full chain

```python
# fragment
# WRONG: Testing a handler with a manually constructed event.
def test_inventory_handler(self):
    event = OrderPlaced(
        order_id="ord-123",
        customer_id="cust-456",
        total=100.0,
    )
    handler = InventoryEventHandler()
    handler.on_order_placed(event)

    # Passes, but in production the event might have different
    # metadata, come from a different stream, or not arrive at all.
```

**Why it's wrong:** The test misses the wiring. A misconfigured `part_of` or
stream category means the handler is never invoked in production, but this
test would still pass.

**Fix:** Use Level 2 sync flow tests to verify the full chain.

### Skipping E2E tests entirely

```python
# fragment
# WRONG: "Our unit tests cover everything."
# No Level 2 or Level 3 tests exist. The team discovers in production
# that the OrderDashboardProjector was never registered, or that
# events are routed to the wrong stream category.
```

**Why it's wrong:** Unit tests cannot verify that components are wired
together correctly. Registration, stream routing, and projection mapping
only surface when the full chain runs.

**Fix:** Add Level 2 sync flow tests for every command-to-projection path.

### Mixing async and sync in the same test

```python
# fragment
# WRONG: Sending a command synchronously but expecting async event processing.
def test_confused_flow(self):
    domain.config["event_processing"] = "async"
    domain.process(PlaceOrder(...))

    # Events were dispatched to the event store, but no engine is running.
    # This assertion will fail because no one is processing events.
    dashboard = domain.view_for(OrderDashboard).get("ord-123")
    assert dashboard is not None  # Fails!
```

**Why it's wrong:** With async event processing, events are written to the
event store but not processed until an engine reads them. Without starting
the engine, the events sit unprocessed.

**Fix:** Either use sync processing (Level 2) or start the engine in test
mode (Level 3) after dispatching the command.

---

## Summary

| Aspect | Level 1: Domain unit | Level 2: Sync flow | Level 3: Async E2E |
|--------|---------------------|-------------------|-------------------|
| **What it tests** | Business logic, events | Full chain wiring | Async infrastructure |
| **Processing mode** | None (direct calls) | `event_processing = "sync"` | `Engine(test_mode=True)` |
| **Speed** | Microseconds | Milliseconds | Seconds |
| **Infrastructure** | None | None | Event store, broker |
| **Deterministic** | Yes | Yes | Yes (runs until every subscription is idle) |
| **Catches** | Logic bugs, wrong events | Wiring, routing, projections | Subscription config, priority lanes, error paths |
| **Test count** | Many (majority) | Some (key flows) | Few (infra-specific) |
| **Typical assertion** | `order.status`, `order._events` | `domain.view_for(P).get(id)` | `domain.view_for(P).get(id)` after `engine.run()` |

Most event-driven flow testing belongs at Level 2. Set `event_processing =
"sync"`, call `domain.process()`, and assert on projection state immediately.
The sync pipeline exercises the same handlers and projectors as production,
without async complexity. Reserve Level 3 for subscription configuration,
priority lanes, and error handling paths.

---

!!! tip "Related reading"
    **Patterns:**

    - [Testing Domain Logic in Isolation](testing-domain-logic-in-isolation.md): Level 1: unit testing domain elements.
    - [Idempotent Event Handlers](idempotent-event-handlers.md): Handlers safe for replay and re-testing.
    - [Dual-Mode Testing](dual-mode-testing.md): Run tests against in-memory and real adapters.

    **Guides:**

    - [Application Tests](../guides/testing/application-tests.md): Testing command handlers and services.
    - [Integration Tests](../guides/testing/integration-tests.md): Full integration testing.
    - [Event Sourcing Tests](../guides/testing/event-sourcing-tests.md): Fluent test DSL for ES aggregates.
