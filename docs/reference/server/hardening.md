# Server Hardening Reference

Every option, default, and metric for server hardening: pool tuning, health
probes, DLQ policy, subscription profiles, OpenTelemetry metrics, shutdown,
and optimistic locking. For the
operational walkthrough that ties these together, see the
[Server Hardening guide](../../guides/server/hardening.md). For the
`--reload` development flag, see [Run the Server](../../guides/server/index.md#hot-reload-in-development).

## Connection pools

### SQLAlchemy providers

Pool defaults for the `postgresql`, `mssql` and `mysql` providers (SQLite uses
`SingletonThreadPool` and ignores these keys).

| Key | Default | Purpose |
|-----|---------|---------|
| `pool_size` | `5` | Base connections kept open per worker |
| `max_overflow` | `10` | Additional temporary connections beyond `pool_size` |
| `pool_recycle` | unset | Recycle connections older than N seconds |

```toml
--8<-- "reference/server/hardening/database_pool.toml"
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
--8<-- "reference/server/hardening/message_db.toml"
```

### LOW_POOL_SIZE warning

`Domain.init()` logs a `LOW_POOL_SIZE` warning for any SQLAlchemy database
with `pool_size < 5` unless `PROTEAN_ENV` is `development` or `testing`. Memory
providers are skipped. The warning is advisory. It does not block startup.

With `pool_size = 2` on a PostgreSQL provider, startup logs:

```
Database 'default' has pool_size=2 (production default is 5). Consider raising it for production workloads.
```

`protean check` does not report this warning, so it does not change the exit
code. Raise `pool_size` or set `PROTEAN_ENV` to `development`/`testing` to
silence the warning.

## Health checks

### `[server.health]`

| Key | Default | Purpose |
|-----|---------|---------|
| `enabled` | `true` | Start the health HTTP server |
| `host` | `"127.0.0.1"` | Bind address (loopback by default; set `"0.0.0.0"` to expose off-host) |
| `port` | `8080` | Listen port |
| `port_auto_increment` | `false` | Try `8081`, `8082`, ... when `port` is taken, so engines can share a host |

### Engine endpoints

| Path | Probe | Response |
|------|-------|----------|
| `GET /healthz` | Liveness | `200` with `{"status": "ok", "checks": {"event_loop": "responsive"}}` |
| `GET /livez` | Liveness (alias for `/healthz`) | Same as `/healthz` |
| `GET /readyz` | Readiness | `200` when all checks pass, `503` otherwise |
| `POST /drainz` | Drain trigger | `200` with `{"status": "draining", "pid": <worker pid>, "drained": <bool>}`; flips the engine to `draining` |

Sample responses. Liveness while the engine is running:

```bash
$ curl -i http://localhost:8080/livez
HTTP/1.1 200 OK
Content-Type: application/json
Content-Length: 55

{"status": "ok", "checks": {"event_loop": "responsive"}}
```

Readiness when every dependency is reachable:

```bash
$ curl -i http://localhost:8080/readyz
HTTP/1.1 200 OK
Content-Type: application/json

{
  "status": "ok",
  "checks": {
    "shutting_down": false,
    "providers": {"default": "ok"},
    "brokers": {"default": "ok"},
    "event_store": "ok",
    "caches": {"default": "ok"},
    "subscriptions": {
      "total": 12,
      "details": [
        {
          "name": "OrderProjector-order",
          "handler_name": "OrderProjector",
          "subscription_type": "stream",
          "stream_category": "order",
          "lag": 0,
          "lag_seconds": 0.0,
          "lag_drain_rate": 0.0,
          "pending": 0,
          "dlq_depth": 0,
          "status": "ok",
          "circuit_state": "closed"
        }
      ]
    }
  }
}
```

The `subscriptions` block reports the same lag and status data as the
`protean subscriptions status` CLI and the `protean.subscription.consumer_lag`
/ `protean.subscription.pending_messages` gauges, with the same field names. It
also reports the circuit-breaker state of each stream subscription.

| Field | Meaning |
|-------|---------|
| `total` | How many subscription objects the engine is running. |
| `details` | One row per subscription found by walking the domain registry. |
| `lag` | Messages behind the stream head, or `null` when it cannot be determined. |
| `lag_seconds` | Seconds behind the stream head, or `null` when it cannot be determined. |
| `lag_drain_rate` | Change in `lag_seconds` per second: negative while the backlog drains, positive while it grows. `null` until two refreshes have finished, or when `lag_seconds` is unknown. |
| `status` | `ok`, `lagging`, or `unknown`. |
| `circuit_state` | `closed`, `open`, or `half_open`. Absent when the subscription has no breaker. |

These points matter to code that reads the `subscriptions` block:

- **`total` and `details` count different things** and may differ in length.
  `total` is the engine's own tally of live subscription objects; `details`
  comes from walking the domain registry. One `sequential_by` process manager,
  for example, is a single engine subscription but one row per stream category.
- **`lag: null` does not always mean trouble**: It means the value could not be
  determined: the backend was unreachable, *or* the consumer group does not
  exist yet because nothing has been consumed. A freshly deployed subscription
  reports `lag: null, status: "unknown"` against a perfectly healthy Redis.
- **An unreadable lag is reported as `null`, never as zero**: If the backend
  cannot be reached, or the lag cannot be computed, the row says
  `lag: null, status: "unknown"` rather than guessing. A `status: "ok"` row means
  the collector read the subscription and found it caught up.
- **`lag_drain_rate` tells you which way lag is moving, not just how big it
  is**: A lag of 40 seconds that is draining at `-2.0` clears on its own; the
  same 40 seconds at `+2.0` is falling further behind and needs attention.
  `lag_drain_rate` is the slope of `lag_seconds` over a short sliding window,
  so it reads `null` for the first refresh after startup (one sample is not a
  trend) and whenever `lag_seconds` itself is `null`. An unreadable lag also
  starts the window over, so the first refresh after the lag becomes readable
  again reads `null` rather than a slope stretched across the gap.
  `lag_drain_rate` is not a metrics gauge: a metrics backend computes the same
  rate of change from `protean_subscription_lag_seconds` with `deriv()`.
- **A partitioned category reports summed lag**: A `sequential_by` subscription
  consumes `{category}:{key}` partition streams, so its row sums lag and
  pending counts across every live partition (`current_position` reports how
  many there are). One halted partition therefore shows up in the total. Lag
  per partition comes from the native `lag` field on Redis 7.0+, and from
  counting entries after the group's last delivered ID on earlier versions. An
  unpartitioned stream uses the same two sources. If neither source can be
  read, the row reports `lag: null`, as it does for any unreadable lag, and
  still sums the pending counts.
- **The FastAPI health router omits the block entirely**, so a script parsing
  both entry points must treat `subscriptions` as optional.

The block is **informational and never changes the verdict**. A lagging
subscription or an open circuit breaker leaves the probe at `200`, because a
backlog is not a reason for Kubernetes to pull the pod out of service: the
engine is healthy and still draining the stream. Alert on lag from the metrics,
not from readiness.

**The probe never collects.** To gather this data, the engine queries
infrastructure once per subscription. Those queries can be slow or hang, so the
engine never runs them on the probe path. A background task refreshes the block
every two seconds and `/readyz` reads the last result out of memory. Answering
a probe therefore costs nothing and cannot fail, no matter what the backends
are doing. The two-second interval sets how often the engine queries Redis and
the event store. It does not change how fast a probe answers.

Three states tell you the data is not current:

- `"collection_pending": true` with empty `details`: the first refresh has not
  finished yet (normal for a second or two after startup).
- `"collection_error": true`: The last refresh raised. The previous block is
  not served in its place, so you are not shown stale numbers as if they were
  fresh.
- `"stale": true` with `"age_seconds"`: no refresh has finished for several
  intervals, which usually means a backend has stopped responding. The last
  good data is still shown, with its age, so you can judge it.

Readiness when one component is unreachable (the status changes to `"degraded"`
and the HTTP code to `503`, which K8s treats as "not ready"):

```bash
$ curl -i http://localhost:8080/readyz
HTTP/1.1 503 Service Unavailable
Content-Type: application/json

{
  "status": "degraded",
  "checks": {
    "shutting_down": false,
    "providers": {"default": "ok"},
    "brokers": {"default": "unavailable"},
    "event_store": "ok",
    "caches": {"default": "ok"},
    "subscriptions": {"total": 12, "details": [...]}
  }
}
```

Readiness after `SIGTERM` arrives (the engine reports `"unavailable"`
immediately, so the load balancer drains traffic before the engine stops
in-flight handlers):

```bash
$ curl -i http://localhost:8080/readyz
HTTP/1.1 503 Service Unavailable
Content-Type: application/json

{"status": "unavailable", "checks": {"shutting_down": true}}
```

`/livez` keeps returning `200` during the drain window; it only fails
when the event loop itself is blocked. This asymmetry is deliberate:
liveness triggers a restart, readiness pulls the pod out of rotation.

### Draining: `POST /drainz`

`POST /drainz` asks the engine to stop taking new work while in-flight work
finishes, without shutting the process down. It flips the engine to a
`draining` state, distinct from the `shutting_down` state a `SIGTERM` sets:

```bash
$ curl -i -X POST http://localhost:8080/drainz
HTTP/1.1 200 OK
Content-Type: application/json

{"status": "draining", "pid": 4021, "drained": false}
```

While draining:

- New messages are no longer fetched: the subscription poll loops stop pulling
  new batches. A batch already read keeps running to completion, so no
  in-flight message is dropped. The loop exits once that batch finishes. The
  message handlers themselves are not gated on `draining` or on
  `shutting_down`, so a message already dispatched is never failed because a
  drain or a shutdown began.
- The outbox keeps flushing while draining, because it holds already-committed
  rows and no new inbound work. It publishes what it has and does not wait for
  the next process to start. It stops on the `SIGTERM` shutdown.
- Partitioned subscriptions stop processing and stop taking on new partitions.
  The discovery loop still renews the leases they already hold, so those leases
  do not expire during the drain. The leases are released on the
  `SIGTERM` shutdown.
- `/readyz` reports not-ready so a load balancer stops routing to the pod. The
  body carries a `draining` marker, kept separate from `shutting_down` so you
  can tell a draining pod from one tearing down:

```bash
$ curl -i http://localhost:8080/readyz
HTTP/1.1 503 Service Unavailable
Content-Type: application/json

{"status": "unavailable", "checks": {"draining": true}}
```

- `/healthz` and `/livez` stay `200`: draining means healthy but not taking
  work, so it is not a restart signal.

The `drained` field is `true` once this worker has no batch in flight. A batch
counts as in flight from the read that fetched it until its last message is
handled, so a subscription waiting on a read also counts. Each `POST` returns
the current value, so a `preStop` hook can repeat the `POST` until the response
reads `true`, then let the `SIGTERM` follow:

```bash
until curl -sX POST http://localhost:8080/drainz | grep -q '"drained": true'; do
  sleep 1
done
```

`/drainz` is advisory. It does not itself shut the engine down; the process
stays alive so your orchestrator can send `SIGTERM` afterwards to actually
stop it. This matches Kubernetes `preStop` semantics: drain in the hook, then
let the termination grace period run the real shutdown. Only `POST /drainz`
drains. A `GET` to the path is an unknown path (`404`), and any other non-`GET`
method still returns `405`.

Draining is a one-way latch. There is no un-drain endpoint: once flipped, the
worker takes in no new messages. Ordinary subscriptions stop pulling and their
poll loops exit. Partitioned subscriptions stop processing and stop acquiring
new partitions, but their discovery loop stays alive to renew the leases they
already hold (as above), so those partitions are not abandoned. The outbox
keeps flushing its committed rows. `/healthz` and `/livez` stay `200` (draining
is not a restart signal), so Kubernetes keeps the pod running but stops routing
traffic to it. Send `SIGTERM` to finish stopping it. The drain trigger needs no
authentication, so keep the health server on `127.0.0.1` (the default) unless
you have a reason to expose it. A stray `POST /drainz` from any reachable
client takes a worker out of service until the worker is stopped.

`/drainz` lives on the engine health server only. The FastAPI health router has
no engine handle and runs in a separate process, so in that process the ASGI
server drains in-flight HTTP requests (for example uvicorn's
graceful shutdown).

#### `/drainz` drains one worker

The drain flag lives on the Engine in the process that answered the request, so
a `POST` drains that worker and no other. With one worker per pod (the usual
Kubernetes shape) that is the whole process and nothing more is needed.

Under `protean server --workers N` it is not. Each worker runs its own engine
and its own health server, and workers share no IPC, so there is no way for one
worker to drain its peers. To drain the whole group, POST to every worker's
health port:

```toml
--8<-- "reference/server/hardening/health.toml"
```

```bash
$ for port in 8080 8081 8082 8083; do curl -sX POST "http://localhost:$port/drainz"; done
{"status": "draining", "pid": 4021, "drained": true}
{"status": "draining", "pid": 4022, "drained": true}
{"status": "draining", "pid": 4023, "drained": false}
{"status": "draining", "pid": 4024, "drained": true}
```

`port_auto_increment` is required here. With the default `false`, only the
first worker binds the configured port. The other workers log a bind failure
and run without probes, so they have no port to POST to. The response carries
the `pid` of the worker that drained, so you can confirm you reached distinct
workers rather than the same one N times. Ports are assigned in bind order, not
worker order, so do not assume port `8080` is worker `0`.

On a multi-worker host, a simpler alternative to `/drainz` is to send `SIGTERM`
to the supervisor. The supervisor propagates it to every worker and runs the
real shutdown, including the `drain_timeout` window described below.

### FastAPI router factory

```python
# fragment
from protean.integrations.fastapi.health import create_health_router

create_health_router(
    domain,                # Domain instance
    *,
    prefix: str = "",      # URL prefix for all health routes
    tags: list[str | Enum] | None = None,  # OpenAPI tags
)
```

Mounts `GET /healthz`, `GET /livez`, and `GET /readyz`. The `/readyz` check
runs the same provider, broker, event-store, and cache inspection as the engine
server. The `/healthz` and `/livez` bodies differ. The FastAPI router returns
`{"status": "ok", "checks": {"application": "running"}}`, since there is no
event-loop task inside the request cycle to probe.

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
--8<-- "reference/server/hardening/001.py:alert_callback"
```

### Per-subscription overrides

Fields on `SubscriptionConfig` that override the global defaults for
a single subscription:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `dlq_retention_hours` | <code>int &#124; None</code> | inherit global | Per-handler retention window |
| `dlq_alert_threshold` | <code>int &#124; None</code> | inherit global | Per-handler alert threshold |

!!! warning "Known issue: per-handler DLQ overrides have no effect yet"
    The subscription config Protean builds for a handler does not carry
    `dlq_retention_hours` or `dlq_alert_threshold`, so the engine applies the
    `[server.dlq]` values to every handler.

The maintenance task only runs when a broker that advertises the
`DEAD_LETTER_QUEUE` capability is configured. Redis Streams implements
time-based trimming via `XTRIM MINID`; other brokers fall back to a
no-op `dlq_trim()`.

## Subscription profiles

Five profiles (`PRODUCTION`, `FAST`, `BATCH`, `DEBUG`, `PROJECTION`) resolve at
engine startup to concrete `SubscriptionConfig` values. For the full
per-profile value dictionaries (`messages_per_tick`, `blocking_timeout_ms`,
`max_retries`, `enable_dlq`, etc.), see [Subscription Configuration → Profile
Defaults](./configuration.md#profile-defaults).

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
| `origin_stream` | <code>str &#124; None</code> | `None` | Both |
| `dlq_retention_hours` | <code>int &#124; None</code> | `None` | `STREAM` |
| `dlq_alert_threshold` | <code>int &#124; None</code> | `None` | `STREAM` |
| `circuit_breaker_threshold` | `int` | `10` | `STREAM` |
| `circuit_breaker_reset_seconds` | `float` | `60` | `STREAM` |

See [Subscription Configuration](./configuration.md) for the full
precedence hierarchy.

## Circuit breaker

Every `StreamSubscription` carries an in-memory circuit breaker that pauses
reads after repeated handler failures, so a failing downstream service gets no
new calls until a probe succeeds. It counts consecutive handler-outcome
failures (a message routed to the DLQ still counts as one failure) and is
separate from `poll()`'s own backoff for broker read errors.

| Key | Default | Purpose |
|-----|---------|---------|
| `circuit_breaker_threshold` | `10` | Consecutive handler failures that trip the breaker OPEN. Must be ≥ 1. |
| `circuit_breaker_reset_seconds` | `60` | Seconds an OPEN breaker waits before a single HALF_OPEN probe. Must be > 0 and finite (`inf`/`nan` are rejected). |

```toml
--8<-- "reference/server/hardening/circuit_breaker.toml"
```

State machine:

- **CLOSED**: Normal operation. Each failure increments the counter;
  the first success resets it to zero. When the counter reaches
  `circuit_breaker_threshold`, the breaker moves to OPEN.
- **OPEN**: Reads are paused. Pending messages stay in the stream/PEL
  for redelivery; the breaker never acks an unprocessed message, so
  nothing is dropped or reordered. On the next poll turn after
  `circuit_breaker_reset_seconds` has elapsed, the breaker moves to
  HALF_OPEN. The poll loop makes the move lazily, with no timer. So if the poll
  loop is in its own error backoff, the move can happen slightly later than the
  exact window.
- **HALF_OPEN**: A single probe message is read. A successful probe
  closes the breaker; a failing probe re-opens it and restarts the reset
  timer.

The breaker is always on. With the default threshold of 10 it only trips
after 10 consecutive handler failures, so healthy workloads are
unaffected. There is no disable flag.

Each transition records the
`protean.subscription.circuit_breaker.state` counter (see below) and
emits a trace event: `subscription.circuit_breaker.opened`,
`subscription.circuit_breaker.closed`, or
`subscription.circuit_breaker.half_open`.

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
| `protean.subscription.circuit_breaker.state` | Counter | `{transition}` | `subscription`, `handler`, `state` (`opened`/`closed`/`half_open`) |
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
3. Wait up to the drain window for in-flight handler tasks to complete;
   cancel any that remain. A batch that started before the shutdown keeps
   handling its messages inside the window. When the window ends, the batch is
   cancelled. Its unhandled messages are not retried and not sent to the
   dead-letter queue: on Redis Streams they stay pending for the next start to
   claim (see [`server.reclaim_idle_seconds`](#serverreclaim_idle_seconds)).
   A partitioned stream subscription (`sequential_by`) is the exception: it
   cancels its partition workers in step 2, and the partition's next owner
   claims their pending messages through the lease handover.
4. Call `Domain.close()`, which closes the event store, brokers, caches, and
   providers in reverse initialisation order.
5. Remove signal handlers and stop the event loop.

`Domain.close()` is callable from application code for tests and
tooling that create and tear down domains on demand.

### `server.drain_timeout`

| Key | Default | Purpose |
|-----|---------|---------|
| `drain_timeout` | `10` | Seconds step 3 waits for in-flight handlers before force-cancelling |

```toml
--8<-- "reference/server/hardening/drain_timeout.toml"
```

The default of `10` preserves the previous fixed behaviour. A zero or negative
value is rejected and falls back to `10`, since it would give in-flight work no
grace at all. So is anything that is not a finite number: a non-numeric string,
a boolean, `nan`, or `inf`.

The multi-worker Supervisor reads the same key from the project config. On
shutdown it waits for the drain window plus 5 seconds before it sends `SIGKILL`
to a worker, and never less than 30 seconds. The extra seconds cover the domain
close and signal-handler cleanup that follow the drain. Single-worker runs have
no supervisor.

The Supervisor reads the config file without importing the domain. It looks in
`DOMAIN_ROOT_PATH` if that is set, then in the directory of the `--domain` file
or package, then in the working directory. The Supervisor cannot read a window
set only in code, such as `Domain(config=...)`, so it waits 30 seconds.

`protean server --reload` reads the same key. The reloader waits for the drain
window plus 5 seconds (never less than 10) before killing the worker it is
restarting, so a longer window is honoured on that path too.

A process manager or orchestrator has its own stop deadline, such as systemd's
`TimeoutStopSec` or Kubernetes' `terminationGracePeriodSeconds`. Set it above
the server's own wait, or it kills the server before the drain ends. For one
worker, that is the drain window plus a few seconds for the steps around it.
For several workers, it is the Supervisor's wait: the larger of 30 and the
drain window plus 5.

### `server.reclaim_idle_seconds`

| Key | Default | Purpose |
|-----|---------|---------|
| `reclaim_idle_seconds` | `120` | Seconds a Redis stream entry must stay unacknowledged before a starting subscription claims it |

A worker can stop in the middle of a batch. The messages it had read and not
yet handled then stay pending in the Redis consumer group, under that worker's
consumer name. Every start uses a new consumer name, so no later read returns
those messages. On startup each stream subscription and broker subscription
claims the group's entries that have stayed unacknowledged for at least
`reclaim_idle_seconds`, then reads and handles them. With priority lanes on,
the stream subscription claims on the backfill stream too. Partitioned
subscriptions claim through their own lease handover and do not
use `reclaim_idle_seconds`.

A claimed message keeps its earlier deliveries toward `max_retries`. Take a
message delivered once before the restart. If it fails once more after the
restart, it reaches `max_retries = 2` and goes to the dead-letter queue.

`reclaim_idle_seconds` must meet two conditions:

- It must be longer than `circuit_breaker_reset_seconds` (60 by default) and
  longer than the longest batch. A consumer that is still running holds its
  entries for that long without acknowledging them. With a shorter threshold, a
  new start can claim those entries and handle them twice.
- Only a start claims entries. Suppose a restart leaves an entry and the worker
  comes back within the threshold. At that start the entry is younger than the
  threshold, so it waits for a later start, or for another worker in the group
  to start.

A zero or negative value falls back to `120`, since a start would then claim
the entries of consumers that are still running. So does anything that is not a
finite number. A failed claim is logged as a warning and does not stop the
subscription from starting.

## Optimistic locking

`ExpectedVersionError` is raised when two writers race for the same
aggregate version. Each adapter makes the version check atomic in its own way:

| Adapter | Mechanism |
|---------|-----------|
| SQLAlchemy repository | Version compared inside the same transaction as the update |
| Elasticsearch repository | Native `if_seq_no` + `if_primary_term` on index operations |
| Memory repository | `threading.Lock` serialises writes |
| Memory event store | `threading.Lock` guards `write()` |
| MessageDB event store | Stored-procedure API enforces expected version inside PostgreSQL |

Command handlers auto-retry on `ExpectedVersionError`; see
[Error Handling](../../guides/server/error-handling.md#version-conflict-auto-retry).
