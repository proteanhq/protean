# Running the Server

This guide covers how to start, configure, and operate the Protean server for
processing async messages in your domain.

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
| `--help` | Show help message | |

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

## Production Deployment

### Process Management

Use a process manager like systemd, supervisord, or Docker:

```ini
# /etc/systemd/system/protean-server.service
[Unit]
Description=Protean Message Server
After=network.target

[Service]
Type=simple
User=app
WorkingDirectory=/app
Environment=PROTEAN_ENV=production
ExecStart=/app/.venv/bin/protean server --domain=my_domain
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install poetry && poetry install

ENV PROTEAN_ENV=production
CMD ["poetry", "run", "protean", "server", "--domain=my_domain"]
```

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: protean-server
spec:
  replicas: 3  # Multiple workers for scaling
  selector:
    matchLabels:
      app: protean-server
  template:
    metadata:
      labels:
        app: protean-server
    spec:
      containers:
      - name: server
        image: my-app:latest
        command: ["protean", "server", "--domain=my_domain"]
        env:
        - name: PROTEAN_ENV
          value: "production"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

### Scaling Considerations

**StreamSubscription** supports horizontal scaling:

- Multiple server instances can run concurrently
- Messages are distributed across consumers via Redis consumer groups
- Each message is processed by exactly one consumer

**EventStoreSubscription** has limited scaling:

- Multiple instances will process the same messages
- Use for projections where idempotency is guaranteed
- Consider using StreamSubscription for scalable workloads

### Health Checks

Add health checks for production deployments:

```python
# health_check.py
import sys
from my_domain import domain

def check_health():
    try:
        # Verify domain can activate
        with domain.domain_context():
            # Check broker connectivity
            broker = domain.brokers.get("default")
            if broker:
                broker.ping()  # If supported

            # Check event store connectivity
            if domain.event_store:
                domain.event_store.store.ping()  # If supported

        return 0
    except Exception as e:
        print(f"Health check failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(check_health())
```

## Logging

### Log Levels

| Level | What's Logged |
|-------|---------------|
| ERROR | Exceptions, failed processing |
| WARNING | Retries, DLQ moves, deprecation warnings |
| INFO | Startup, shutdown, batch summaries |
| DEBUG | Message details, position updates, config resolution |

### Configuring Logging

```python
import logging

# Set log level for Protean server
logging.getLogger("protean.server").setLevel(logging.DEBUG)

# Or configure via logging config
LOGGING_CONFIG = {
    "version": 1,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "detailed",
        }
    },
    "formatters": {
        "detailed": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s"
        }
    },
    "loggers": {
        "protean.server": {
            "level": "DEBUG",
            "handlers": ["console"],
        }
    }
}
```

### Structured Logging

For production, consider structured logging:

```python
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
```

## Monitoring

Protean includes a built-in monitoring server called the **Observatory** that
provides real-time visibility into the message processing pipeline.

### Protean Observatory

Start the Observatory alongside your engine to get a dashboard, REST API,
SSE stream, and Prometheus metrics endpoint:

```python
from protean.server.observatory import Observatory

observatory = Observatory(domains=[domain])
observatory.run(port=9000)
```

The Observatory exposes:

| Endpoint | Description |
|----------|-------------|
| `GET /` | Live HTML dashboard |
| `GET /stream` | SSE real-time trace events (filterable) |
| `GET /api/health` | Broker health, version, memory, ops/sec |
| `GET /api/outbox` | Outbox message counts per domain |
| `GET /api/streams` | Stream lengths and consumer groups |
| `GET /api/stats` | Combined throughput statistics |
| `GET /metrics` | Prometheus text exposition format |

### Key metrics

Monitor these metrics in production (available at `/metrics`):

| Metric | Description |
|--------|-------------|
| `protean_broker_up` | Broker health (1=up, 0=down) |
| `protean_outbox_messages` | Outbox messages by domain and status |
| `protean_stream_messages_total` | Total messages across all streams |
| `protean_stream_pending` | In-flight (unacknowledged) messages |
| `protean_broker_ops_per_sec` | Broker operations per second |
| `protean_broker_memory_bytes` | Broker memory usage |

### Prometheus scrape configuration

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'protean'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:9000']
```

For the full observability guide including trace events, SSE filtering, and
zero-overhead design, see [Observability](observability.md).

## Next Steps

- [Engine Architecture](engine.md) - Understand engine internals
- [Observability](observability.md) - Tracing, Observatory server, and Prometheus metrics
- [Configuration](configuration.md) - Full configuration reference
- [Subscription Types](subscription-types.md) - Choose the right subscription
