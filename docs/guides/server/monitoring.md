# Monitoring

Protean includes a built-in monitoring server called the **Observatory** that
provides real-time visibility into the message processing pipeline.

For basic server usage, see [Run the Server](./index.md). For production
deployment patterns, see [Production Deployment](./production-deployment.md).

## Protean Observatory

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
| `GET /api/subscriptions` | Subscription lag, pending, DLQ per handler |
| `GET /metrics` | Prometheus text exposition format |

## Key metrics

Monitor these metrics in production (available at `/metrics`):

| Metric | Description |
|--------|-------------|
| `protean_broker_up` | Broker health (1=up, 0=down) |
| `protean_outbox_messages` | Outbox messages by domain and status |
| `protean_stream_messages_total` | Total messages across all streams |
| `protean_stream_pending` | In-flight (unacknowledged) messages |
| `protean_broker_ops_per_sec` | Broker operations per second |
| `protean_broker_memory_bytes` | Broker memory usage |
| `protean_subscription_lag` | Per-subscription lag behind stream head |
| `protean_subscription_pending` | Per-subscription unacknowledged messages |
| `protean_subscription_dlq_depth` | Per-subscription dead letter queue depth |

## Monitoring subscription lag

Check if subscriptions are falling behind from the CLI without starting the
Observatory:

```bash
protean subscriptions status --domain=my_app
```

Or query the Observatory's REST API:

```bash
curl http://localhost:9000/api/subscriptions
```

For Prometheus alerting, use `protean_subscription_lag` to detect handlers
that are falling behind:

```yaml
# prometheus alert rule
groups:
  - name: protean
    rules:
      - alert: SubscriptionLagging
        expr: protean_subscription_lag > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Subscription {{ $labels.handler }} is lagging"
```

See [`protean subscriptions`](../../reference/cli/runtime/subscriptions.md)
for full CLI documentation.

## Prometheus scrape configuration

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'protean'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:9000']
```

For the full observability guide including trace events, SSE filtering, and
zero-overhead design, see [Observability](../../reference/server/observability.md).
