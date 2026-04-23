# Harden the server for production

This guide walks through the operational steps of taking a Protean
domain to production: raising connection pools, exposing Kubernetes
health probes, enabling DLQ maintenance, picking subscription profiles,
emitting OpenTelemetry metrics, and shutting down gracefully. For the
full catalogue of options, defaults, metric names, and profile values,
see the [Server Hardening reference](../../reference/server/hardening.md).

## Raise connection pool limits

Out-of-the-box SQLAlchemy defaults (`pool_size = 5`, `max_overflow =
10`) are sized for a single worker against a small database. Bump them
before you go live:

```toml
[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"
pool_size = 10
max_overflow = 20
pool_recycle = 1800
```

Do the same for the Redis broker and cache so their `ConnectionPool`
scales with request volume:

```toml
[brokers.default]
provider = "redis"
URI = "${REDIS_URL}"
max_connections = 50

[caches.default]
provider = "redis"
URI = "${REDIS_URL}"
max_connections = 50
```

Run `protean check` before deploying. It surfaces a `LOW_POOL_SIZE`
warning for SQLAlchemy databases configured below the production
default, and catches other misconfigurations at the same time.

## Expose health probes to Kubernetes

### Async engine (`protean server`)

The engine embeds a lightweight HTTP server on port `8080` by default.
No configuration is needed unless you want to move the port, bind to a
different interface, or turn the server off; to override, add a
`[server.health]` section to `domain.toml`:

```toml
[server.health]
host = "0.0.0.0"
port = 8080
```

Wire the probes into your Deployment:

```yaml
containers:
- name: server
  image: my-app:latest
  command: ["protean", "server", "--domain=my_domain"]
  ports:
  - containerPort: 8080
    name: health
  livenessProbe:
    httpGet: { path: /livez, port: health }
    periodSeconds: 10
  readinessProbe:
    httpGet: { path: /readyz, port: health }
    periodSeconds: 5
```

`/livez` proves the event loop is responsive; `/readyz` inspects every
provider, broker, cache, and the event store, and returns `503` when
any component is unhealthy or the engine is shutting down.

### FastAPI apps

Mount the equivalent router on your API process:

```python
from fastapi import FastAPI
from protean.integrations.fastapi.health import create_health_router

app = FastAPI()
app.include_router(create_health_router(domain))
```

The router exposes the same `/healthz`, `/livez`, and `/readyz` paths
with the same readiness semantics as the engine server.

## Keep the DLQ under control

By default, messages that exhaust their retries pile up in
`{stream}:dlq` forever. Enable the maintenance task to trim old entries
and alert when a queue grows:

```toml
[server.dlq]
enabled = true
retention_hours = 168          # Keep 7 days of history
alert_threshold = 100          # Warn when depth hits 100
alert_callback = "myapp.alerts.on_dlq_alert"
```

The alert callback runs inside the engine; keep it cheap and
non-blocking (page the on-call rotation, post to Slack, open a
ticket). Time-based trimming requires a Redis Streams broker.

Override retention or alerting per handler when a subscription needs
different SLAs — for example, an auditing handler that must keep 30
days of failures:

```python
@domain.event_handler(
    part_of=Order,
    subscription_config={
        "dlq_retention_hours": 720,
        "dlq_alert_threshold": 10,
    },
)
class AuditHandler(BaseEventHandler):
    ...
```

For discovery, inspection, and replay of individual DLQ messages, see
[Dead Letter Queues](./dead-letter-queues.md).

## Pick a subscription profile

Every handler resolves to a `SubscriptionConfig` at startup. Pick a
profile that matches its workload instead of tuning fields one at a
time:

```python
from protean.server.subscription.profiles import SubscriptionProfile

@domain.event_handler(
    part_of=Order,
    subscription_profile=SubscriptionProfile.PRODUCTION,
)
class OrderEventHandler(BaseEventHandler):
    ...
```

Override individual fields without abandoning the profile:

```python
@domain.event_handler(
    part_of=Order,
    subscription_profile=SubscriptionProfile.PRODUCTION,
    subscription_config={"messages_per_tick": 50},
)
class BulkOrderHandler(BaseEventHandler):
    ...
```

## Emit OpenTelemetry metrics

Install the telemetry extra and enable it in `domain.toml`:

```bash
pip install "protean[telemetry]"
```

```toml
[telemetry]
enabled = true
exporter = "otlp"
endpoint = "http://otel-collector:4317"
service_name = "my-service"
```

The engine emits per-subscription counters and histograms
(`protean.subscription.messages_processed`,
`protean.subscription.processing_duration`, …), DLQ maintenance
counters (`protean.dlq.trimmed`, `protean.dlq.alerts`), and engine
gauges (`protean.engine.up`, `protean.engine.uptime_seconds`, …)
directly through the OTLP exporter.

Connection-pool and backpressure gauges
(`protean.db.pool_*`, `protean.broker.pool_active_connections`,
`protean.subscription.consumer_lag`) are lazily registered on the
Observatory's `/metrics` endpoint. Scrape it with Prometheus
alongside your OTLP exporter — see [Monitoring](./monitoring.md).

Every metric is a no-op when `opentelemetry-api` is not installed.

## Shut down gracefully

`protean server` handles `SIGINT`, `SIGTERM`, and `SIGHUP` by stopping
the health server, signalling every subscription and outbox processor
to stop, waiting up to 10 seconds for in-flight handlers to finish,
then closing the event store, brokers, caches, and providers in
reverse initialisation order. Send `SIGTERM` and give the pod a
`terminationGracePeriodSeconds` of at least `15` — long enough for
the drain and close steps to complete:

```yaml
spec:
  terminationGracePeriodSeconds: 30
  containers:
  - name: server
    lifecycle:
      preStop:
        exec:
          command: ["sleep", "5"]  # Let the load balancer drain
```

When you create and tear down domains from test or tooling code, call
`domain.close()` yourself:

```python
from my_domain import domain

try:
    with domain.domain_context():
        # ... do work ...
finally:
    domain.close()
```

Custom adapters inherit a no-op `close()`; override it when your
adapter holds sockets, file handles, or background threads.

## See also

- [Server Hardening reference](../../reference/server/hardening.md) — every option, default, and metric catalogued.
- [Production Deployment](./production-deployment.md) — process management, Docker, and Kubernetes manifests.
- [Error Handling](./error-handling.md) — retry flow per subscription type and version-conflict auto-retry.
- [Dead Letter Queues](./dead-letter-queues.md) — inspect, replay, and purge DLQ entries.
- [OpenTelemetry Integration](./opentelemetry.md) — exporter setup, TraceParent propagation, and the full span catalogue.
