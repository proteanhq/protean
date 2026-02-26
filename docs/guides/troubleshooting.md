# Troubleshooting

A cookbook of common issues and how to debug them. For error classification
patterns in production, see
[Classify Async Processing Errors](../patterns/classify-async-processing-errors.md).

---

## Command is accepted but nothing happens

**Symptoms:** `domain.process()` returns without error, but the aggregate
isn't created or updated.

**Check 1: Is there a handler registered?**

```python
# In a test or shell, after domain.init()
with domain.domain_context():
    handlers = domain.command_handler_for(PlaceOrder)
    print(handlers)  # Should show your handler class
```

If this returns `None`, the handler isn't registered. Verify:

- The handler is decorated with `@domain.command_handler(part_of=YourAggregate)`
- The handler file is inside the domain's discovery path
- `domain.init()` was called after registration

**Check 2: Is the handler actually persisting?**

Command handlers must explicitly save via the repository:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order(customer_id=command.customer_id)
        # This line is required -- without it, nothing is persisted
        current_domain.repository_for(Order).add(order)
```

**Check 3: Is event processing set to sync for tests?**

In tests, events are processed asynchronously by default. If your test
expects immediate side effects, configure sync processing:

```python
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"
```

Or use the `DomainFixture` which handles this automatically.

---

## Event handler doesn't fire

**Symptoms:** An aggregate raises an event, but the event handler's method
is never called.

**Check 1: Is the event raised inside the aggregate?**

Events must be raised with `self.raise_()` inside an aggregate method:

```python
class Order(BaseAggregate):
    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(order_id=self.id))  # Required
```

Simply creating an event object does nothing -- it must be raised.

**Check 2: Is the handler wired to the right aggregate?**

```python
# The handler must declare part_of matching the event's aggregate
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced):
        ...
```

If the event belongs to `Order` but the handler says `part_of=Customer`,
it won't receive the event.

**Check 3: Is event processing async?**

In production, events flow through the outbox and are processed by the
server. In tests, set `event_processing = "sync"` or use the Engine in
test mode:

```python
from protean.server import Engine

engine = Engine(domain=domain, test_mode=True)
engine.run()
```

---

## "No domain context" errors

**Symptoms:** `RuntimeError: Working outside of domain context` or similar.

**Cause:** Protean operations require an active domain context on the current
thread. This is usually set up by middleware (FastAPI) or fixtures (tests).

**Fix for FastAPI:**

```python
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)
```

**Fix for tests:**

```python
@pytest.fixture(autouse=True)
def domain_context(test_domain):
    with test_domain.domain_context():
        yield
```

**Fix for scripts or CLI tools:**

```python
with domain.domain_context():
    repo = domain.repository_for(Order)
    orders = repo.all()
```

---

## Projection is empty or stale

**Symptoms:** Querying a projection returns no results or outdated data,
even though events have been raised.

**Check 1: Is the projector registered?**

```python
@domain.projector(part_of=OrderSummary)
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced):
        current_domain.repository_for(OrderSummary).add(
            OrderSummary(order_id=event.order_id, ...)
        )
```

Verify the projector is decorated with `@domain.projector` and uses
`part_of` pointing to the projection class.

**Check 2: Are events flowing?**

In tests, ensure sync processing is active or run the engine:

```python
engine = Engine(domain=domain, test_mode=True)
engine.run()
```

**Check 3: Is the projection database set up?**

Projections backed by a database need schema setup:

```python
with domain.domain_context():
    domain.setup_database()
```

---

## Subscriber doesn't receive messages

**Symptoms:** External messages are published to the broker, but the
subscriber's `__call__` method is never invoked.

**Check 1: Is the stream name correct?**

The subscriber's `stream` must match the broker stream/topic being published
to:

```python
@domain.subscriber(stream="external_orders")
class OrderSubscriber:
    def __call__(self, payload: dict):
        ...
```

**Check 2: Is the broker configured?**

Verify your `domain.toml` has a broker configured:

```toml
[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"
```

**Check 3: Is the server running?**

Subscribers are processed by the Protean server, not inline. Start it with:

```bash
protean server --domain .
```

For tests, use test mode to process messages synchronously.

---

## Aggregate validation errors

**Symptoms:** `ValidationError` when creating or updating an aggregate.

**Debugging approach:**

```python
try:
    order = Order(customer_id="", total=-5)
except ValidationError as e:
    print(e.messages)
    # {'customer_id': ['is required'], 'total': ['must be positive']}
```

The `messages` dict maps field names to lists of error strings. Common
causes:

- **Missing required fields:** Fields with `required=True` must be provided
- **Invariant violations:** `@invariant.post` checks run after every mutation
- **Value object validation:** Embedded value objects validate their own
  constraints

---

## Message tracing and debugging event chains

When a command triggers a chain of events and handlers, use Protean's
built-in tracing to follow the full causal chain.

**From the CLI:**

```bash
# Trace a specific correlation ID
protean events trace <correlation_id> --domain .
```

**Programmatically:**

```python
from protean.utils.eventing import build_causation_tree

with domain.domain_context():
    tree = build_causation_tree(correlation_id)
    # Returns nested dict of command → events → handler effects
```

**Supply correlation IDs from API boundaries:**

```python
@app.post("/orders")
async def create_order(request: Request, payload: dict):
    request_id = request.headers.get("X-Request-Id")
    current_domain.process(
        PlaceOrder(**payload),
        correlation_id=request_id,  # Thread through the chain
    )
```

See [Message Tracing](./domain-behavior/message-tracing.md) for the full
guide.

---

## Common CLI debugging commands

```bash
# Check subscription status and lag
protean subscriptions --domain .

# Inspect dead letter queue
protean dlq list --domain .

# View recent events for an aggregate
protean events list --stream order-<aggregate_id> --domain .

# Launch the observatory dashboard
protean observatory --domain .
```

---

## Tests pass locally but fail in CI

**Common causes:**

1. **Missing Docker services:** Broker/database tests need Redis,
   PostgreSQL, etc. Use `make up` or configure CI to start services.

2. **Async timing:** Tests relying on async processing may need explicit
   engine runs. Use `engine.run()` in test mode rather than `time.sleep()`.

3. **Database state leakage:** Ensure each test starts clean. The
   `DomainFixture` handles this, but custom fixtures might not.

4. **Port conflicts:** If multiple CI jobs run in parallel, broker/database
   ports may collide. Use unique port mappings per job.

---

## Getting more help

- Check the [patterns](../patterns/index.md) for architectural guidance
- Review the [API reference](../api/index.md) for detailed method signatures
- File issues at [github.com/proteanhq/protean](https://github.com/proteanhq/protean/issues)
