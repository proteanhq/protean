# Chapter 18: Monitoring Subscription Health

After the DLQ incident in Chapter 17, the team realizes they need to
know about problems *before* customers call support. We need proactive
monitoring of the message processing pipeline.

## Checking Subscription Status

The quickest way to check health is the CLI:

```shell
$ protean subscriptions status --domain bookshelf
Subscription                  Stream                    Lag    Pending  DLQ
BookCommandHandler            bookshelf::book:command   0      0        0
OrderCommandHandler           bookshelf::order:command  0      0        0
BookEventHandler              bookshelf::book           0      0        0
OrderEventHandler             bookshelf::order          2      1        0
BookCatalogProjector          bookshelf::book           0      0        0
BookReportProjector           bookshelf::book-fact      0      0        3
```

Key metrics:

- **Lag** — messages waiting to be processed. High lag means the handler
  is falling behind.
- **Pending** — messages currently being processed (acknowledged but not
  yet completed).
- **DLQ** — messages that failed all retries.

## The Observatory Dashboard

For real-time monitoring, use the Observatory:

```shell
$ protean observatory --domain bookshelf --host 0.0.0.0 --port 9000
Observatory running at http://0.0.0.0:9000
Monitoring domains: bookshelf
```

Open `http://localhost:9000` in your browser to see:

- **Subscription status** — lag, pending, and DLQ counts for every
  handler.
- **Processing rates** — messages processed per second.
- **Error rates** — recent failures and their handlers.
- **Live trace stream** — server-sent events showing message processing
  in real time.

The Observatory can monitor multiple domains simultaneously:

```shell
$ protean observatory \
  --domain bookshelf \
  --domain inventory_service \
  --host 0.0.0.0 --port 9000
```

## Metrics Endpoint

The Observatory exposes a `/metrics` endpoint in Prometheus format:

```shell
$ curl http://localhost:9000/metrics
# HELP protean_subscription_lag Messages waiting to be processed
# TYPE protean_subscription_lag gauge
protean_subscription_lag{domain="bookshelf",handler="BookEventHandler"} 0
protean_subscription_lag{domain="bookshelf",handler="OrderEventHandler"} 2
...
```

Connect this to Prometheus and Grafana for production dashboards and
alerting.

## Setting Up Alerts

A basic Prometheus alert for subscription lag:

```yaml
groups:
  - name: bookshelf
    rules:
      - alert: HighSubscriptionLag
        expr: protean_subscription_lag > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Handler {{ $labels.handler }} has high lag"
```

## What We Built

- **`protean subscriptions status`** for quick health checks.
- The **Observatory dashboard** for real-time monitoring.
- A **Prometheus metrics endpoint** for production alerting.
- Understanding of key metrics: lag, pending, DLQ depth.

In the next chapter, we will tackle a bulk import scenario that requires
priority lanes to avoid starving production traffic.

## Next

[Chapter 19: The Great Catalog Import — Priority Lanes →](19-priority-lanes.md)
