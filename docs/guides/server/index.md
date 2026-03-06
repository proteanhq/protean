# Run the Server

This guide covers how to start, configure, and operate Protean's async
processing server — the background process that runs event handlers, command
handlers, and projectors.

For the conceptual architecture behind the server, see
[Async Processing](../../concepts/async-processing/index.md).

## CLI Command

Start the server using the `protean server` command:

```bash
protean server [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Path to domain module | `.` (current directory) |
| `--test-mode` | Run in test mode | `False` |
| `--debug` | Enable debug logging | `False` |
| `--workers` | Number of worker processes | `1` |
| `--help` | Show help message | |

## Database Setup

Before starting the server, ensure your database tables are created:

```bash
# Create all tables (aggregates, entities, projections, outbox)
protean db setup --domain=my_domain

# Create only outbox tables (useful when migrating to stream subscriptions)
protean db setup-outbox --domain=my_domain

# Drop all tables (requires confirmation)
protean db drop --domain=my_domain
protean db drop --domain=my_domain --yes  # Skip confirmation

# Delete all data, preserving schema (requires confirmation)
protean db truncate --domain=my_domain
protean db truncate --domain=my_domain --yes  # Skip confirmation
```

See [Database Commands](../../reference/cli/data/database.md) for the full reference.

## Basic Usage

### Starting the Server

```bash
# Start with domain in current directory
protean server

# Start with specific domain path
protean server --domain=src/my_domain

# Start with module path
protean server --domain=my_package.my_domain

# Start with specific instance
protean server --domain=my_domain:custom_domain
```

### Multiple Workers

Run multiple Engine processes from a single command using `--workers`:

```bash
# Start 4 worker processes
protean server --domain=my_domain --workers 4
```

Workers coordinate through Redis consumer groups (for stream message
distribution) and database-level locking (for outbox processing). No IPC or
shared memory is needed between workers.

For the full multi-worker guide including architecture, coordination details,
and deployment patterns, see [Multi-Worker Mode](../../reference/server/supervisor.md).

### Domain Discovery

The server discovers your domain in this order:

1. **Environment variable**: `PROTEAN_DOMAIN` if set
2. **--domain parameter**: Path or module specified
3. **Current directory**: Looks for `domain.py` or `subdomain.py`

Within a module, it looks for:

1. Variable named `domain` or `subdomain`
2. Any variable that is a `Domain` instance
3. Raises error if multiple instances found

### Debug Mode

Enable verbose logging for troubleshooting:

```bash
protean server --domain=my_domain --debug
```

Debug mode logs:

- Subscription registration details
- Message processing events
- Position updates
- Configuration resolution

### Test Mode

Test mode processes available messages and exits, useful for integration tests:

```bash
protean server --domain=my_domain --test-mode
```

In test mode, the server:

1. Starts all subscriptions and processors
2. Runs multiple processing cycles
3. Allows message chain propagation
4. Shuts down after processing completes

## Using Test Mode in Tests

Test mode enables deterministic testing of async message flows:

```python
import pytest
from protean.server import Engine

def test_order_creates_inventory_reservation():
    """Test that creating an order reserves inventory."""
    # Arrange: Create order (raises events)
    with domain.domain_context():
        order = Order.create(
            customer_id="123",
            items=[OrderItem(product_id="ABC", quantity=5)]
        )
        domain.repository_for(Order).add(order)

    # Act: Process events in test mode
    engine = Engine(domain, test_mode=True)
    engine.run()

    # Assert: Verify inventory was reserved
    with domain.domain_context():
        reservation = domain.repository_for(Reservation).get_by_order(order.id)
        assert reservation is not None
        assert reservation.quantity == 5
```

### Testing Multi-Step Flows

Test mode handles cascading events automatically:

```python
def test_order_fulfillment_flow():
    """Test complete order fulfillment flow."""
    # Order created -> Inventory reserved -> Payment processed -> Order shipped

    with domain.domain_context():
        order = Order.create(...)
        domain.repository_for(Order).add(order)

    # Process all cascading events
    engine = Engine(domain, test_mode=True)
    engine.run()

    with domain.domain_context():
        order = domain.repository_for(Order).get(order.id)
        assert order.status == "shipped"
```

## Programmatic Usage

You can also start the engine programmatically:

```python
from protean.server import Engine
from my_domain import domain

# Create and run the engine
engine = Engine(domain)
engine.run()  # Blocking call
```

### With Custom Options

```python
engine = Engine(
    domain,
    test_mode=False,
    debug=True,
)
engine.run()
```

### Accessing Engine State

```python
engine = Engine(domain)

# Check subscriptions
print(f"Handler subscriptions: {len(engine._subscriptions)}")
print(f"Broker subscriptions: {len(engine._broker_subscriptions)}")
print(f"Outbox processors: {len(engine._outbox_processors)}")

# Access subscription factory
factory = engine.subscription_factory
```

## Signal Handling

The server handles shutdown signals gracefully:

| Signal | Behavior |
|--------|----------|
| `SIGINT` (Ctrl+C) | Graceful shutdown |
| `SIGTERM` | Graceful shutdown |
| `SIGHUP` | Graceful shutdown |

During graceful shutdown:

1. Stop accepting new messages
2. Complete processing of current batch
3. Persist subscription positions
4. Clean up resources
5. Exit with appropriate code

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Normal shutdown (signal or test mode completion) |
| 1 | Error during processing |

## Next Steps

- [Production Deployment](./production-deployment.md) — Process management, Docker, Kubernetes, scaling, and health checks
- [Logging](./logging.md) — Structured logging with structlog, environment-aware defaults, and context variables
- [Monitoring](./monitoring.md) — Observatory dashboard, Prometheus metrics, and subscription lag tracking
- [Multi-Worker Mode](../../reference/server/supervisor.md) — Run multiple Engine processes for higher throughput
- [Engine Architecture](../../concepts/async-processing/engine.md) — Understand engine internals
- [Configuration](../../reference/server/configuration.md) — Full configuration reference
- [Subscription Types](../../reference/server/subscription-types.md) — Choose the right subscription
- [Using Priority Lanes](using-priority-lanes.md) — Route background workloads through the backfill lane
- [External Event Dispatch](external-event-dispatch.md) — Deliver published events to external brokers
