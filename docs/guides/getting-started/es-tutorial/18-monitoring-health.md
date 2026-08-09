# Chapter 18: Monitoring Subscription Health

After the DLQ incident, the team realizes they need **proactive monitoring**.
They should know when a handler is falling behind or accumulating failures, not
discover it from a customer complaint.

## Checking Subscription Status

The `protean subscriptions status` command gives a dashboard of all
subscriptions:

```shell
$ protean subscriptions status --domain=fidelis
                    Subscriptions - Fidelis
 Handler                     Type    Stream                Lag  Pending  DLQ  Status
 AccountCommandHandler       stream  fidelis::account:cmd    0        0    -  ok
 AccountSummaryProjector     stream  fidelis::account        2        0    -  ok
 ComplianceAlertHandler      stream  fidelis::account        0        0    3  lagging
 NotificationHandler         stream  fidelis::account        0        0    -  ok
 AccountReportProjector      stream  fidelis::account-fact   0        0    -  ok
 FundsTransferPM             stream  fidelis::transfer       0        0    -  ok

6 subscription(s), 5 ok, 1 lagging, total lag: 2
```

Key metrics:

- **Lag**: How many messages the handler has not yet processed. High
  lag means the handler is falling behind.
- **Pending**: Messages currently being processed (claimed but not
  acknowledged).
- **DLQ**: Number of messages in the dead-letter queue.
- **Status**: `ok`, `lagging`, or `unknown`.

For machine-readable output:

```shell
$ protean subscriptions status --domain=fidelis --json
```

## The Observatory

For real-time monitoring, launch the **Observatory**, Protean's built-in
observability dashboard:

```shell
$ protean observatory --domain=fidelis --port=9000
Observatory running at http://0.0.0.0:9000
```

The Observatory provides:

- **Live message traces**: A real-time stream of `handler.started`,
  `handler.completed`, `handler.failed`, `message.acked`,
  `message.dlq` events via Server-Sent Events.
- **Subscription status**: The same data as the CLI, auto-refreshing
  every 5 seconds.
- **DLQ management**: Inspect, replay, and purge directly from the
  web interface.
- **Stream health**: Queue depths per stream.

### Observatory API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard |
| `GET /stream` | SSE real-time trace stream |
| `GET /api/health` | Health check |
| `GET /api/subscriptions` | Subscription status |
| `GET /api/traces` | Recent trace history |
| `GET /api/streams` | Stream information |
| `GET /api/outbox` | Outbox status |
| `GET /metrics` | Prometheus metrics |

## Prometheus Metrics

The Observatory exposes Prometheus-compatible metrics at `/metrics`:

```
# HELP protean_subscription_lag Messages behind head position
# TYPE protean_subscription_lag gauge
protean_subscription_lag{domain="fidelis",handler="AccountSummaryProjector",stream="fidelis::account",type="stream"} 2

# HELP protean_subscription_dlq_depth Messages in dead-letter queue
# TYPE protean_subscription_dlq_depth gauge
protean_subscription_dlq_depth{domain="fidelis",handler="ComplianceAlertHandler",stream="fidelis::account",type="stream"} 3

# HELP protean_subscription_status Subscription status (1=ok, 0=error)
# TYPE protean_subscription_status gauge
protean_subscription_status{domain="fidelis",handler="AccountCommandHandler",stream="fidelis::account:command",type="stream"} 1
```

These metrics can be scraped by Grafana, Datadog, or any Prometheus-
compatible monitoring tool. Set alerts on:

- `protean_subscription_lag > 100`: Handler falling behind
- `protean_subscription_dlq_depth > 0`: Failed messages accumulating

## Trace Events

The engine emits structured trace events for every message processed:

- `handler.started`: Handler began processing a message
- `handler.completed`: Handler finished successfully
- `handler.failed`: Handler threw an exception
- `message.acked`: Message acknowledged (removed from pending)
- `message.nacked`: Message negatively acknowledged (will retry)
- `message.dlq`: Message moved to dead-letter queue
- `outbox.published`: Outbox processor published a message to broker
- `outbox.failed`: Outbox processor failed to publish

These events flow to the Observatory via Redis Pub/Sub in real-time.
When nobody is listening, the emitter short-circuits with zero overhead.

## What We Built

- **`protean subscriptions status`** for quick health checks.
- The **Observatory** for real-time monitoring and DLQ management.
- **Prometheus metrics** for production alerting.
- Understanding of **trace events** emitted by the engine.

With monitoring in place, we can detect problems early. In the next chapter, a
bank acquisition triggers a massive migration, and we learn how to handle it
without disrupting production.

## Next

[Chapter 19: The Great Migration, Run on Priority Lanes →](19-priority-lanes.md)
