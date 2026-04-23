# Server Hardening Reference

Every option, default, and metric shipped by the Server Hardening epic
— pool tuning, health probes, DLQ policy, subscription profiles,
OpenTelemetry metrics, shutdown, and optimistic locking. For the
operational walkthrough that ties these together, see the
[Server Hardening guide](../../guides/server/hardening.md). For the
`--reload` development flag, see [Run the Server](../../guides/server/index.md#hot-reload-in-development).

## Connection pools

### SQLAlchemy providers

Pool defaults for `postgresql` and `mssql` providers (SQLite uses
`SingletonThreadPool` and ignores these keys).

| Key | Default | Purpose |
|-----|---------|---------|
| `pool_size` | `5` | Base connections kept open per worker |
| `max_overflow` | `10` | Additional temporary connections beyond `pool_size` |
| `pool_recycle` | unset | Recycle connections older than N seconds |

```toml
[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"
pool_size = 10
max_overflow = 20
pool_recycle = 1800
```

### Redis broker and cache

Both adapters forward pool parameters to `redis.ConnectionPool`.

| Key | Purpose |
|-----|---------|
| `max_connections` | Cap on connections in the pool |
| `socket_timeout` | Read/write timeout, seconds |
| `socket_connect_timeout` | Connection timeout, seconds |
| `retry_on_timeout` | Retry reads that time out |

### MessageDB event store

Forward `max_connections` directly through `conn_info`.

```toml
[event_store]
provider = "message_db"
database_uri = "${MESSAGE_DB_URL}"
max_connections = 20
```

### LOW_POOL_SIZE warning

`Domain.check()` emits a `LOW_POOL_SIZE` warning for any SQLAlchemy
database with `pool_size < 5` unless `PROTEAN_ENV` is `development` or
`testing`. Memory providers are skipped. The warning is advisory — it
does not block startup.

## Health checks

### `[server.health]`

| Key | Default | Purpose |
|-----|---------|---------|
| `enabled` | `true` | Start the health HTTP server |
| `host` | `"0.0.0.0"` | Bind address |
| `port` | `8080` | Listen port |

### Engine endpoints

| Path | Probe | Response |
|------|-------|----------|
| `GET /healthz` | Liveness | `200` with `{"status": "ok", "checks": {"event_loop": "responsive"}}` |
| `GET /livez` | Liveness (alias for `/healthz`) | Same as `/healthz` |
| `GET /readyz` | Readiness | `200` when all checks pass, `503` otherwise |

`/readyz` body:

```json
{
  "status": "ok",
  "checks": {
    "shutting_down": false,
    "providers": {"default": "ok"},
    "brokers": {"default": "ok"},
    "event_store": "ok",
    "caches": {"default": "ok"},
    "subscriptions": 12
  }
}
```

`status` is `"ok"` when every dependency check passes, `"degraded"`
when any component fails, and `"unavailable"` when the engine is
already shutting down.

### FastAPI router factory

```python
from protean.integrations.fastapi.health import create_health_router

create_health_router(
    domain,                # Domain instance
    *,
    prefix: str = "",      # URL prefix for all health routes
    tags: list[str] | None = None,  # OpenAPI tags
)
```

Mounts `GET /healthz`, `GET /livez`, and `GET /readyz`. The `/readyz`
check runs the same provider, broker, event-store, and cache inspection
as the engine server. The `/healthz` and `/livez` bodies differ — the
FastAPI router returns `{"status": "ok", "checks": {"application":
"running"}}`, since there is no event-loop task inside the request
cycle to probe.

## Dead-letter queue policy

### `[server.dlq]`

| Key | Default | Purpose |
|-----|---------|---------|
| `enabled` | `false` | Start the DLQ maintenance task |
| `retention_hours` | `168` (7 days) | Trim DLQ entries older than this |
| `alert_threshold` | `100` | Log a warning when DLQ depth ≥ this |
| `alert_callback` | unset | Dotted path to a callable, invoked on alert |
| `check_interval_seconds` | `60` | Seconds between maintenance cycles |

The alert callback is invoked with keyword arguments:

```python
def on_dlq_alert(dlq_stream: str, depth: int, threshold: int) -> None:
    ...
```

### Per-subscription overrides

Fields on `SubscriptionConfig` that override the global defaults for
a single subscription:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `dlq_retention_hours` | `int \| None` | inherit global | Per-handler retention window |
| `dlq_alert_threshold` | `int \| None` | inherit global | Per-handler alert threshold |

The maintenance task only runs when a broker that advertises the
`DEAD_LETTER_QUEUE` capability is configured. Redis Streams implements
time-based trimming via `XTRIM MINID`; other brokers fall back to a
no-op `dlq_trim()`.

## Subscription profiles

Profile defaults resolved at engine startup.

| Profile | Subscription type | `messages_per_tick` | `blocking_timeout_ms`[^1] | `max_retries`[^1] | `enable_dlq` |
|---------|-------------------|---------------------|----------------------------|--------------------|--------------|
| `PRODUCTION` | `STREAM` | 100 | 5000 | 3 | true |
| `FAST` | `STREAM` | 10 | 100 | 2 | true |
| `BATCH` | `STREAM` | 500 | 10000 | 5 | true |
| `DEBUG` | `STREAM` | 1 | 1000 | 1 | false |
| `PROJECTION` | `EVENT_STORE` | 100 | 5000 | 3 | false |

[^1]: Ignored for `EVENT_STORE` subscriptions.

`SubscriptionConfig` fields resolvable at every precedence level:

| Field | Type | Default | Applies to |
|-------|------|---------|------------|
| `subscription_type` | `SubscriptionType` | `STREAM` | — |
| `messages_per_tick` | `int` | `10` | Both |
| `tick_interval` | `int` | `0` | Both |
| `blocking_timeout_ms` | `int` | `5000` | `STREAM` |
| `max_retries` | `int` | `3` | `STREAM` |
| `retry_delay_seconds` | `float` | `1.0` | `STREAM` |
| `enable_dlq` | `bool` | `true` | `STREAM` |
| `position_update_interval` | `int` | `10` | `EVENT_STORE` |
| `origin_stream` | `str \| None` | `None` | Both |
| `dlq_retention_hours` | `int \| None` | `None` | `STREAM` |
| `dlq_alert_threshold` | `int \| None` | `None` | `STREAM` |

See [Subscription Configuration](./configuration.md) for the full
precedence hierarchy.

## OpenTelemetry metrics

Every metric below is registered on `DomainMetrics` and emitted as a
no-op when `opentelemetry-api` is not installed. For the exporter and
propagation setup, see
[OpenTelemetry Integration](../../guides/server/opentelemetry.md).

### Per-subscription counters and histograms

Emitted directly by the engine.

| Metric | Type | Unit | Attributes |
|--------|------|------|------------|
| `protean.subscription.messages_processed` | Counter | `{message}` | `subscription`, `handler`, `stream`, `status` (`ok`/`error`) |
| `protean.subscription.retries` | Counter | `{retry}` | `subscription`, `handler`, `stream` |
| `protean.subscription.dlq_routed` | Counter | `{message}` | `subscription`, `handler`, `stream` |
| `protean.subscription.processing_duration` | Histogram | `s` | `subscription`, `handler`, `stream` |

### Engine gauges

Emitted directly by the engine.

| Metric | Type | Unit | Meaning |
|--------|------|------|---------|
| `protean.engine.up` | Observable gauge | `1` | `1` while running, `0` during shutdown |
| `protean.engine.uptime_seconds` | Observable gauge | `s` | Seconds since the engine started |
| `protean.engine.active_subscriptions` | Observable gauge | `{subscription}` | Current count of live subscriptions |

### DLQ maintenance counters

Emitted by `DLQMaintenanceTask`.

| Metric | Type | Unit | Attributes |
|--------|------|------|------------|
| `protean.dlq.trimmed` | Counter | `{message}` | `dlq_stream` |
| `protean.dlq.alerts` | Counter | `{alert}` | `dlq_stream` |

### Infrastructure gauges (Observatory `/metrics`)

Lazily registered on the first scrape of the Observatory's Prometheus
endpoint. See [Observability](./observability.md).

| Metric | Type | Attributes |
|--------|------|------------|
| `protean.db.pool_size` | Observable gauge | `provider_name`, `database_type` |
| `protean.db.pool_checked_out` | Observable gauge | `provider_name`, `database_type` |
| `protean.db.pool_overflow` | Observable gauge | `provider_name`, `database_type` |
| `protean.db.pool_checked_in` | Observable gauge | `provider_name`, `database_type` |
| `protean.broker.pool_active_connections` | Observable gauge | `broker_name` |
| `protean.subscription.consumer_lag` | Observable gauge | `domain`, `handler`, `stream`, `type` |
| `protean.subscription.pending_messages` | Observable gauge | `domain`, `handler`, `stream`, `type` |
| `protean.outbox.pending_count` | Observable gauge | `domain` |

`BaseProvider.pool_stats()` returns `{size, checked_out, overflow,
checked_in}`. SQLAlchemy providers return live counts; memory and
Elasticsearch providers return an empty dict.

## Shutdown sequence

`Engine.shutdown()` runs these steps on `SIGINT`, `SIGTERM`, or
`SIGHUP`:

1. Stop the health HTTP server (probes start failing immediately).
2. Signal every subscription, broker subscription, outbox processor,
   and DLQ maintenance task to stop.
3. Wait up to **10 seconds** for in-flight handler tasks to complete;
   cancel any that remain.
4. Call `Domain.close()` — closes event store, brokers, caches, and
   providers in reverse initialisation order.
5. Remove signal handlers and stop the event loop.

`Domain.close()` is callable from application code for tests and
tooling that create and tear down domains on demand.

## Optimistic locking

`ExpectedVersionError` is raised when two writers race for the same
aggregate version. Atomicity guarantees per adapter:

| Adapter | Mechanism |
|---------|-----------|
| SQLAlchemy repository | Version compared inside the same transaction as the update |
| Elasticsearch repository | Native `if_seq_no` + `if_primary_term` on index operations |
| Memory repository | `threading.Lock` serialises writes |
| Memory event store | `threading.Lock` guards `write()` |
| MessageDB event store | Stored-procedure API enforces expected version inside PostgreSQL |

Command handlers auto-retry on `ExpectedVersionError`; see
[Error Handling](../../guides/server/error-handling.md#version-conflict-auto-retry).
