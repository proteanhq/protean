# Test Event-Driven Flows End-to-End

## The Problem

Unit testing individual domain elements is straightforward. You construct an
aggregate, call a method, assert the resulting state. The
[Testing Domain Logic in Isolation](testing-domain-logic-in-isolation.md)
pattern covers this well. But real event-driven systems are not made of isolated
pieces -- they are made of *chains*:

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
Work commit -- in the same thread, in the same process, with no async
machinery.

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
executes three deterministic processing cycles with 0.1-second sleeps between
them, then performs a graceful shutdown. No `time.sleep()` guesswork.

```python
engine = Engine(domain, test_mode=True)
engine.run()

# Engine has processed all pending messages across 3 cycles
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
| Business logic correctness | Yes | -- | -- |
| Event payloads and structure | Yes | -- | -- |
| Command-to-handler wiring | -- | Yes | -- |
| Event-to-handler routing | -- | Yes | -- |
| Projection updates | -- | Yes | -- |
| Multi-step event chains | -- | Yes | Yes |
| Subscription configuration | -- | -- | Yes |
| Priority lane routing | -- | -- | Yes |
| Error handling paths | -- | -- | Yes |
| Outbox processing | -- | -- | Yes |

Level 2 covers most integration needs. It runs at unit-test speed because
there is no event loop, no network, and no async coordination. Reserve Level 3
for the small number of tests that truly need the async Engine.

---

## Applying the Pattern

The examples below use a consistent e-commerce domain: an `Order` aggregate
that raises `OrderPlaced`, an `InventoryEventHandler` that reserves stock, and
an `OrderDashboard` projection that tracks order status.

### Domain setup

```python
from protean import Domain
from protean.fields import Auto, Float, Identifier, Integer, String
from protean.utils.globals import current_domain

domain = Domain(__file__, "ecommerce")


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float(default=0.0)

    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total=self.total,
        ))


@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    total = Float(required=True)


@domain.command(part_of=Order)
class PlaceOrder(BaseCommand):
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    total = Float(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            total=command.total,
        )
        order.place()
        repo.add(order)


@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(event.customer_id)
        inventory.reserve(order_id=event.order_id)
        repo.add(inventory)


@domain.projection
class OrderDashboard(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_id = Identifier()
    status = String()
    total = Float()


@domain.projector(projector_for=OrderDashboard, aggregates=[Order])
class OrderDashboardProjector(BaseProjector):

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderDashboard)
        repo.add(OrderDashboard(
            order_id=event.order_id,
            customer_id=event.customer_id,
            status="placed",
            total=event.total,
        ))
```

### Test fixtures

A `conftest.py` that initializes the domain with sync processing and provides
a per-test context:

```python
# tests/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from ecommerce.domain import domain


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

### Level 1: Domain unit tests

Test the aggregate's business logic and event raising directly:

```python
import pytest


class TestOrderPlacement:
    """Level 1: Test aggregate behavior in isolation."""

    def test_placing_order_transitions_status(self):
        order = Order(
            customer_id="cust-123",
            total=99.95,
        )

        order.place()

        assert order.status == "placed"

    def test_placing_order_raises_order_placed_event(self):
        order = Order(
            customer_id="cust-123",
            total=99.95,
        )

        order.place()

        assert len(order._events) == 1
        event = order._events[0]
        assert isinstance(event, OrderPlaced)
        assert event.order_id == order.order_id
        assert event.customer_id == "cust-123"
        assert event.total == 99.95
```

These tests run in microseconds. They verify that `Order.place()` produces
the correct state and the correct event payload.

### Level 2: Sync flow tests

Test the full command-to-projection chain with sync processing:

```python
class TestOrderFlowSync:
    """Level 2: Test the full chain with sync event processing."""

    def test_place_order_updates_projection(self):
        """Command -> handler -> aggregate -> event -> projector -> projection."""
        domain.process(
            PlaceOrder(
                order_id="ord-001",
                customer_id="cust-123",
                total=99.95,
            )
        )

        # Projection is updated synchronously -- no sleep, no engine
        view = domain.view_for(OrderDashboard)
        dashboard = view.get("ord-001")

        assert dashboard is not None
        assert dashboard.status == "placed"
        assert dashboard.customer_id == "cust-123"
        assert dashboard.total == 99.95

    def test_event_chain_fires_downstream_handlers(self):
        """Verify that OrderPlaced triggers InventoryEventHandler."""
        # Pre-populate inventory
        repo = domain.repository_for(Inventory)
        repo.add(Inventory(product_id="prod-1", available_quantity=100))

        domain.process(
            PlaceOrder(
                order_id="ord-003",
                customer_id="cust-123",
                total=50.0,
            )
        )

        # In sync mode, the InventoryEventHandler fires inline
        # during the same UoW commit that persists the Order
        inventory = repo.get("prod-1")
        # Assert that the handler processed the event
        assert inventory is not None
```

These tests verify the **wiring**: commands reach handlers, events reach
projectors, and projections reflect the correct state. They run at near
unit-test speed because sync processing has no async overhead.

### Level 3: Async E2E tests

Test the async engine for scenarios that require the full infrastructure:

```python
import pytest

from protean.server.engine import Engine


@pytest.mark.no_test_domain
class TestOrderFlowAsync:
    """Level 3: Test with the real async Engine in test mode."""

    @pytest.fixture(autouse=True)
    def setup_domain(self):
        """Initialize the domain with async processing for engine tests."""
        domain.config["event_processing"] = "async"
        domain.config["command_processing"] = "sync"

        domain.init()
        with domain.domain_context():
            yield

    def test_full_async_flow(self):
        """Command -> handler -> event -> engine processes -> projection updated."""
        # Submit the command (sync command processing, async event processing)
        domain.process(
            PlaceOrder(
                order_id="ord-async-001",
                customer_id="cust-123",
                total=75.00,
            )
        )

        # Run the engine in test mode: 3 deterministic cycles, then shutdown
        engine = Engine(domain, test_mode=True)
        engine.run()

        # After engine.run() completes, all pending events have been processed
        view = domain.view_for(OrderDashboard)
        dashboard = view.get("ord-async-001")

        assert dashboard is not None
        assert dashboard.status == "placed"
        assert dashboard.total == 75.00

        # Also verify the aggregate was persisted through the chain
        order = domain.repository_for(Order).get("ord-async-001")
        assert order.status == "placed"
```

### Testing error handling paths

Level 3 is essential for testing `handle_error()` overrides:

```python
@domain.event_handler(part_of=Inventory)
class FailingInventoryHandler(BaseEventHandler):
    """A handler that deliberately fails, for testing error classification."""

    _errors_captured: list = []

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        raise ConnectionError("Database temporarily unavailable")

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        cls._errors_captured.append({
            "exception": exc,
            "message_type": type(message).__name__,
        })


@pytest.mark.no_test_domain
class TestErrorHandling:
    """Level 3: Verify error classification and handle_error behavior."""

    @pytest.fixture(autouse=True)
    def setup_domain(self):
        domain.config["event_processing"] = "async"
        domain.init()
        with domain.domain_context():
            FailingInventoryHandler._errors_captured.clear()
            yield

    def test_handle_error_receives_exception(self):
        """Verify that handle_error is called when a handler raises."""
        domain.process(
            PlaceOrder(
                order_id="ord-err-001",
                customer_id="cust-123",
                total=50.0,
            )
        )

        engine = Engine(domain, test_mode=True)
        engine.run()

        # The handler failed, but handle_error captured the exception
        assert len(FailingInventoryHandler._errors_captured) > 0
        captured = FailingInventoryHandler._errors_captured[0]
        assert isinstance(captured["exception"], ConnectionError)
        assert "temporarily unavailable" in str(captured["exception"])
```

### Testing priority lane routing

```python
from protean.utils.processing import Priority


@pytest.mark.no_test_domain
class TestPriorityLanes:
    """Level 3: Verify priority-based event routing."""

    @pytest.fixture(autouse=True)
    def setup_domain(self):
        domain.config["event_processing"] = "async"
        domain.config["server"] = {
            "priority_lanes": {"enabled": True, "threshold": Priority.NORMAL},
        }
        domain.init()
        with domain.domain_context():
            yield

    def test_backfill_events_route_to_backfill_lane(self):
        """Events below the threshold are routed to the backfill stream."""
        domain.process(
            PlaceOrder(
                order_id="ord-pri-001",
                customer_id="cust-456",
                total=50.0,
            ),
            priority=Priority.BACKFILL,
        )

        # In test mode with 3 cycles, backfill events are still processed
        # (the primary stream is empty, so the backfill stream is polled).
        engine = Engine(domain, test_mode=True)
        engine.run()

        view = domain.view_for(OrderDashboard)
        dashboard = view.get("ord-pri-001")
        assert dashboard is not None
```

---

## Anti-Patterns

### Using `time.sleep()` for synchronization

```python
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
| **Deterministic** | Yes | Yes | Yes (3 fixed cycles) |
| **Catches** | Logic bugs, wrong events | Wiring, routing, projections | Subscription config, priority lanes, error paths |
| **Test count** | Many (majority) | Some (key flows) | Few (infra-specific) |
| **Typical assertion** | `order.status`, `order._events` | `domain.view_for(P).get(id)` | `domain.view_for(P).get(id)` after `engine.run()` |

The principle: **most event-driven flow testing belongs at Level 2. Set
`event_processing = "sync"`, call `domain.process()`, and assert on projection
state immediately. The sync pipeline exercises the same handlers and projectors
as production -- without async complexity. Reserve Level 3 for subscription
configuration, priority lanes, and error handling paths.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Testing Domain Logic in Isolation](testing-domain-logic-in-isolation.md) -- Level 1: unit testing domain elements.
    - [Idempotent Event Handlers](idempotent-event-handlers.md) -- Handlers safe for replay and re-testing.
    - [Dual-Mode Testing](dual-mode-testing.md) -- Run tests against in-memory and real adapters.

    **Guides:**

    - [Application Tests](../guides/testing/application-tests.md) -- Testing command handlers and services.
    - [Integration Tests](../guides/testing/integration-tests.md) -- Full integration testing.
    - [Event Sourcing Tests](../guides/testing/event-sourcing-tests.md) -- Fluent test DSL for ES aggregates.
