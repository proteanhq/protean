# OpenTelemetry integration

Protean ships with native OpenTelemetry (OTel) support for distributed tracing
and metrics. When enabled, command processing, event handling, repository
operations, and server message dispatch automatically emit OTel spans and
metrics -- plugging into any APM backend (Datadog, Jaeger, Grafana Tempo, etc.)
with zero user code changes.

## Installation

Install the telemetry extras alongside Protean:

```bash
pip install "protean[telemetry]"
```

This pulls in:

- `opentelemetry-api` and `opentelemetry-sdk`
- `opentelemetry-exporter-otlp-proto-grpc` (OTLP exporter)
- `opentelemetry-instrumentation-fastapi` (HTTP span auto-instrumentation)
- `opentelemetry-exporter-prometheus` (`/metrics` convergence)

## Configuration

Enable telemetry in your `domain.toml`:

```toml
[telemetry]
enabled = true
service_name = "my-service"   # Defaults to the domain's normalized name
exporter = "otlp"             # "otlp" (default) or "console"
endpoint = "http://localhost:4317"  # OTLP collector endpoint (optional)
```

### Configuration keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Master switch for all OTel instrumentation |
| `service_name` | string | domain name | Populates the `service.name` resource attribute |
| `exporter` | string | `"otlp"` | Span and metric exporter: `"otlp"` or `"console"` |
| `endpoint` | string | SDK default | OTLP collector endpoint (gRPC) |
| `resource_attributes` | table | `{}` | Additional OTel resource attributes merged into the `Resource` |

### Resource attributes

Add arbitrary resource attributes for your APM:

```toml
[telemetry]
enabled = true

[telemetry.resource_attributes]
"deployment.environment" = "production"
"service.version" = "1.2.0"
"team.name" = "platform"
```

These attributes appear on every span and metric exported by the domain.

## Zero-overhead guarantee

When telemetry is disabled (the default) or the `opentelemetry` packages are
not installed, all instrumentation is a no-op:

1. **No imports at module level** -- the `opentelemetry` package is imported
   lazily inside `src/protean/utils/telemetry.py` and only when enabled.
2. **No-op fallbacks** -- `domain.tracer` and `domain.meter` return lightweight
   no-op objects (`_NoOpTracer`, `_NoOpMeter`) whose methods do nothing.
3. **Context managers still work** -- every `with tracer.start_as_current_span()`
   call works identically whether real or no-op, so instrumented code never
   needs conditional guards.

The rest of the codebase never imports `opentelemetry` directly -- all OTel
interaction flows through `protean.utils.telemetry`.

---

## Automatic tracing

Protean instruments key operations across every layer of the stack. Each
instrumentation point creates an OTel span with relevant attributes.

### Span catalog

#### Command processing

| Span name | Emitted by | Description |
|-----------|-----------|-------------|
| `protean.command.enrich` | `CommandProcessor.enrich()` | Command enrichment (identity, metadata, TraceParent injection) |
| `protean.command.process` | `CommandProcessor.process()` | Full command processing lifecycle |

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `protean.command.type` | string | Command class type identifier |
| `protean.command.id` | string | Command message ID |
| `protean.stream` | string | Target stream name |
| `protean.handler.name` | string | Resolved handler class name |

#### Handler execution

| Span name | Emitted by | Description |
|-----------|-----------|-------------|
| `protean.handler.execute` | `HandlerMixin._handle()` | Individual handler method execution |

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `protean.handler.name` | string | Handler class name |
| `protean.handler.type` | string | Element type (`command_handler`, `event_handler`, `projector`, etc.) |

#### Query dispatch

| Span name | Emitted by | Description |
|-----------|-----------|-------------|
| `protean.query.dispatch` | `QueryProcessor.dispatch()` | Query handler dispatch |

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `protean.query.type` | string | Query class type identifier |
| `protean.handler.name` | string | Query handler class name |

#### Data layer

| Span name | Emitted by | Description |
|-----------|-----------|-------------|
| `protean.repository.add` | Repository / EventSourcedRepository | Persist an aggregate |
| `protean.repository.get` | Repository / EventSourcedRepository | Load an aggregate by identity |
| `protean.event_store.append` | EventStore port | Append events/commands to the event store |
| `protean.uow.commit` | UnitOfWork | Commit a Unit of Work transaction |

**Repository attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `protean.aggregate.type` | string | Aggregate class name |
| `protean.provider` | string | Database provider name (CRUD repositories) |
| `protean.repository.kind` | string | `"event_sourced"` for ES repositories |
| `protean.aggregate.id` | string | Aggregate identity value |

**Event store attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `protean.event_store.stream` | string | Stream name |
| `protean.event_store.type` | string | Event/command type |
| `protean.event_store.position` | int | Resulting stream position |

**UoW attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `protean.uow.event_count` | int | Total events gathered |
| `protean.uow.session_count` | int | Number of database sessions committed |

#### Server and outbox

| Span name | Emitted by | Description |
|-----------|-----------|-------------|
| `protean.engine.handle_message` | Engine | Top-level message processing in the server |
| `protean.outbox.process` | OutboxProcessor | Batch outbox processing tick |
| `protean.outbox.publish` | OutboxProcessor | Individual outbox message publish |

**Engine attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `protean.handler.name` | string | Handler class name |
| `protean.message.type` | string | Message class name |
| `protean.message.id` | string | Message UUID |
| `protean.stream_category` | string | Stream category |
| `protean.worker_id` | string | Worker process ID (multi-worker mode) |
| `protean.subscription_type` | string | `command_dispatcher`, `event_handler`, `command_handler`, or `process_manager` |

**Outbox attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `protean.outbox.batch_size` | int | Number of messages in the batch |
| `protean.outbox.processor_id` | string | Subscription identifier |
| `protean.outbox.is_external` | bool | Whether this is an external broker dispatch |
| `protean.outbox.message_id` | string | Individual message ID |
| `protean.outbox.stream_category` | string | Target stream |
| `protean.outbox.message_type` | string | Message class name |
| `protean.outbox.successful_count` | int | Successfully published messages in batch |
| `protean.outbox.skipped` | bool | Message skipped (already published) |

### Span hierarchy

When the server processes a message, spans form a clean parent-child tree:

```
protean.engine.handle_message          (Engine)
  └── protean.handler.execute          (HandlerMixin)
        ├── protean.repository.get     (Repository)
        ├── protean.repository.add     (Repository)
        └── protean.uow.commit         (UnitOfWork)
              └── protean.event_store.append  (EventStore)
```

For command dispatch:

```
protean.command.process                (CommandProcessor)
  └── protean.handler.execute          (HandlerMixin)
        ├── protean.repository.add     (Repository)
        └── protean.uow.commit         (UnitOfWork)
```

All spans are created with `record_exception=False` and
`set_status_on_exception=False` so that Protean can record errors with precise
context using `set_span_error()` from `protean.utils.telemetry`.

---

## Metrics

When telemetry is enabled, Protean records domain-operation metrics through
OTel counters and histograms. These are created lazily per domain via the
`DomainMetrics` class.

### Metrics catalog

#### Counters

| Metric name | Unit | Description |
|-------------|------|-------------|
| `protean.command.processed` | `{command}` | Commands processed |
| `protean.handler.invocations` | `{invocation}` | Handler invocations |
| `protean.uow.commits` | `{commit}` | UoW commits |
| `protean.outbox.published` | `{message}` | Outbox messages published |
| `protean.outbox.failed` | `{message}` | Outbox publish failures |

#### Histograms

| Metric name | Unit | Description |
|-------------|------|-------------|
| `protean.command.duration` | `s` | Command processing latency |
| `protean.handler.duration` | `s` | Handler execution latency |
| `protean.uow.events_per_commit` | `{event}` | Events gathered per UoW commit |
| `protean.outbox.latency` | `s` | Time from outbox write to publish |

All metrics carry labels like `command_type`, `handler_name`, and
`stream_category` for grouping in your APM dashboard.

---

## TraceParent propagation

Protean propagates distributed trace context across message boundaries using
the W3C `traceparent` header format.

### How it works

1. **Injection** -- When a command is enriched (`CommandProcessor.enrich()`),
   the current OTel span context is serialized into a `TraceParent` value
   object and stored in `message.metadata.headers.traceparent`.

2. **Storage** -- The `TraceParent` header travels with the message through
   the event store or broker, surviving serialization/deserialization.

3. **Extraction** -- When the Engine processes a message
   (`handle_message()`), it extracts the `TraceParent` from message headers
   and passes it as the parent OTel context to
   `tracer.start_as_current_span()`.

This means a single distributed trace can span:

```
HTTP request (FastAPI)
  └── protean.command.process          (API server)
        └── protean.handler.execute    (API server, sync)
              └── protean.uow.commit   (API server)

    ... message persisted, picked up by server ...

protean.engine.handle_message          (Server, links to same trace)
  └── protean.handler.execute          (Server)
        └── protean.uow.commit         (Server)
```

The key functions are in `protean.utils.telemetry`:

- `inject_traceparent_from_context()` -- captures the current span as a
  `TraceParent` value object
- `extract_context_from_traceparent(traceparent)` -- converts a `TraceParent`
  back to an OTel `Context`

---

## FastAPI auto-instrumentation

Protean provides a one-line integration to instrument your FastAPI application
with OpenTelemetry:

```python
from protean.integrations.fastapi import instrument_app

instrument_app(app, domain)
```

This wraps `opentelemetry-instrumentation-fastapi` and uses the domain's
tracer and meter providers, so HTTP request spans automatically become parents
of any command/event processing spans created during the request.

### What gets instrumented

- Every HTTP request creates a span with standard semantic conventions
  (`http.method`, `http.route`, `http.status_code`)
- These HTTP spans parent `protean.command.process` and
  `protean.handler.execute` spans via OTel context propagation
- Incoming `traceparent` headers from upstream services are respected

### Options

```python
instrument_app(
    app,
    domain,
    excluded_urls="health,ready",  # Skip health check endpoints
)
```

The call is safe even when `opentelemetry` is not installed -- it returns
`False` and logs a warning.

### Excluding Observatory endpoints

When the Observatory runs alongside your application, you may want to exclude
its endpoints from tracing to avoid noise:

```python
instrument_app(app, domain, excluded_urls="metrics,stream,api/health")
```

---

## `/metrics` endpoint convergence

The Observatory's `/metrics` endpoint (Prometheus text exposition format) is
aware of OTel. When telemetry is enabled and `opentelemetry-exporter-prometheus`
is installed:

1. A `PrometheusMetricReader` is attached to the domain's `MeterProvider`
2. All OTel counters, histograms, and infrastructure gauges are served via
   `prometheus_client.generate_latest()`
3. Infrastructure metrics (outbox, broker health, subscription lag) are
   registered as `ObservableGauge` callbacks on the OTel meter

When OTel is **not** enabled, the endpoint falls back to the original
hand-rolled Prometheus implementation with identical behavior. No
configuration change is needed -- the convergence is automatic.

---

## Observatory vs OpenTelemetry

Protean offers two complementary observability paths:

| | Observatory | OpenTelemetry |
|---|---|---|
| **Audience** | Developer running `protean server` locally | Ops team shipping telemetry to Grafana/Datadog |
| **Infrastructure** | Zero-config (Redis already present) | Requires collector + backend + visualization |
| **Data model** | Flat `MessageTrace` events in time-ordered stream | Parent-child span trees with context propagation |
| **Query patterns** | XRANGE by handler/stream/time window | TraceQL/PromQL in external tool |
| **Real-time** | SSE via Redis Pub/Sub | Not applicable (batch export) |
| **Install** | Built-in (needs Redis broker) | `pip install "protean[telemetry]"` |

### When to use which

- **Observatory** -- Local development and debugging. Real-time SSE dashboard,
  REST API for trace history, zero configuration beyond having Redis.
- **OpenTelemetry** -- Production monitoring. Vendor-agnostic spans and metrics
  exported to your APM platform. Distributed tracing across service boundaries.

They share instrumentation callsites but have independent emission paths. Both
can run simultaneously -- the Observatory's trace emitter and OTel spans are
emitted from the same code points in the Engine and handlers without
interference.

---

## APM setup guides

### Jaeger

Run Jaeger all-in-one with OTLP support:

```bash
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest
```

Configure your domain:

```toml
[telemetry]
enabled = true
exporter = "otlp"
endpoint = "http://localhost:4317"
```

Open `http://localhost:16686` to view traces.

### Grafana Tempo + Grafana

```yaml
# docker-compose.yml (excerpt)
services:
  tempo:
    image: grafana/tempo:latest
    ports:
      - "4317:4317"   # OTLP gRPC
      - "3200:3200"   # Tempo API
    command: ["-config.file=/etc/tempo.yml"]

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_AUTH_ANONYMOUS_ENABLED=true
```

Point Protean at Tempo's OTLP endpoint:

```toml
[telemetry]
enabled = true
endpoint = "http://localhost:4317"
```

### Datadog

Use the Datadog Agent's OTLP ingest:

```toml
[telemetry]
enabled = true
exporter = "otlp"
endpoint = "http://localhost:4317"

[telemetry.resource_attributes]
"deployment.environment" = "production"
```

Configure the Datadog Agent to accept OTLP gRPC on port 4317.

### Console exporter (debugging)

For quick local debugging without an APM backend:

```toml
[telemetry]
enabled = true
exporter = "console"
```

Spans and metrics are printed to stdout.

---

## Next steps

- [Observability reference](../../reference/server/observability.md) -- Full
  Observatory API, trace events, and Prometheus metric reference
- [Monitoring](./monitoring.md) -- Observatory setup, key metrics, alerting
- [FastAPI Integration](../fastapi/index.md) -- Domain context middleware and
  exception handlers
- [Engine Architecture](../../concepts/async-processing/engine.md) -- How the
  engine manages subscriptions and lifecycle
