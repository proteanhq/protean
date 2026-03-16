# ADR-0008: Centralized Telemetry Gateway and TraceParent Bridging

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-16 |
| **Author** | Subhash Bhushan |
| **Epic** | 6.1 OpenTelemetry Integration (#742) |

## Context

### The optional dependency problem

OpenTelemetry is an optional dependency in Protean (`pip install
protean[telemetry]`). Instrumentation code -- span creation, metric
recording, context propagation -- is woven into core modules like
`CommandProcessor`, `UnitOfWork`, `Repository`, `Engine`, and
`OutboxProcessor`. Without a clear boundary, every instrumented file
would need its own `try: import opentelemetry ... except ImportError`
guard and conditional logic, scattering OTEL awareness across dozens
of files.

During the Epic 6.1 implementation (8 PRs over multiple weeks), code
review caught at least four instances where contributors directly
imported `opentelemetry` in instrumented modules (`mixins.py`,
`command_processor.py`, `observatory/metrics.py`, `fastapi/telemetry.py`).
Each was corrected by adding a helper to the central module. This
demonstrated that the boundary needs to be explicit and well-documented,
not just a convention.

### The distributed tracing problem

Protean is an asynchronous, message-driven framework. A single user
action can span multiple processing steps:

```
HTTP POST /orders
  -> CommandProcessor.process(PlaceOrder)
    -> CommandHandler raises OrderPlaced event
      -> UnitOfWork commits, writes to outbox
        -> OutboxProcessor publishes to event store
          -> Engine picks up event, dispatches to EventHandler
            -> EventHandler dispatches ReduceInventory command
              -> ...
```

Each arrow may cross a process boundary (via event store or broker).
For a distributed trace to survive this journey, the trace context must
be explicitly carried in message metadata and extracted/injected at each
boundary. Protean already had a `TraceParent` value object in
`MessageHeaders` using W3C format -- but it was not connected to OTEL's
context propagation. The challenge was bridging these two systems
bidirectionally without coupling core domain code to OTEL imports.

## Decision

### Part 1: Centralized telemetry gateway

All OpenTelemetry interaction is funneled through a single module:
`src/protean/utils/telemetry.py`. The rest of the codebase **never
imports `opentelemetry` directly**.

The gateway exposes a fixed public API:

| Function | Purpose |
|----------|---------|
| `init_telemetry(domain)` | One-time provider setup |
| `shutdown_telemetry(domain)` | Flush and tear down |
| `get_tracer(domain)` | Domain-scoped tracer (or no-op) |
| `get_meter(domain)` | Domain-scoped meter (or no-op) |
| `get_tracer_provider(domain)` | Raw provider for advanced use |
| `get_meter_provider(domain)` | Raw provider for advanced use |
| `get_domain_metrics(domain)` | Cached `DomainMetrics` instance |
| `get_prometheus_text(domain)` | Prometheus exposition format |
| `set_span_error(span, exc)` | Record exception + set ERROR status |
| `extract_context_from_traceparent(tp)` | TraceParent VO -> OTEL Context |
| `inject_traceparent_from_context()` | Current OTEL span -> TraceParent VO |
| `create_observation(gauge, value, attrs)` | Observable gauge callback helper |
| `instrument_fastapi_app(app, domain)` | FastAPI auto-instrumentation |

When OTEL packages are not installed or telemetry is disabled, every
function returns a lightweight no-op: `_NoOpTracer`, `_NoOpSpan`,
`_NoOpMeter`, `_NoOpCounter`, `_NoOpHistogram`, `_NoOpObservableGauge`.
These implement the minimal interface that instrumentation code depends
on (e.g., `start_as_current_span()` returns a context manager yielding
`_NoOpSpan`). Instrumentation code calls `tracer.start_as_current_span()`
unconditionally and gets either a real span or a no-op -- no conditional
guards anywhere.

### Part 2: Span conventions

All spans follow the naming pattern `protean.<subsystem>.<operation>`:

| Span Name | Subsystem | Set By |
|-----------|-----------|--------|
| `protean.command.process` | Command processing | `CommandProcessor` |
| `protean.command.enrich` | Command enrichment | `CommandProcessor` |
| `protean.handler.execute` | Handler dispatch | `HandlerMixin` |
| `protean.query.dispatch` | Query dispatch | `QueryProcessor` |
| `protean.uow.commit` | Transaction commit | `UnitOfWork` |
| `protean.repository.add` | Aggregate persistence | `BaseRepository` |
| `protean.repository.get` | Aggregate retrieval | `BaseRepository` |
| `protean.event_store.append` | Event store write | `BaseEventStore` |
| `protean.engine.handle_message` | Server message handling | `Engine` |
| `protean.outbox.process` | Outbox batch | `OutboxProcessor` |
| `protean.outbox.publish` | Outbox single publish | `OutboxProcessor` |

All spans are created with `record_exception=False,
set_status_on_exception=False`. Errors are recorded explicitly via
`set_span_error(span, exc)` in exception handlers. This gives precise
control over what gets recorded and keeps the `StatusCode` import
centralized in the gateway module.

### Part 3: Bidirectional TraceParent bridging

Distributed traces flow across Protean's message boundaries through
three cooperative injection/extraction points:

**Injection (outgoing messages):**

1. **Command enrichment** (`CommandProcessor.enrich()`) -- calls
   `inject_traceparent_from_context()` to capture the current OTEL span
   context as a `TraceParent` value object in the command's
   `MessageHeaders.traceparent`.

2. **Event raising** (`BaseAggregate.raise_()`) -- preserves an existing
   `traceparent` from the event's metadata if present (e.g., when the
   event was constructed with explicit headers). Falls back to
   `inject_traceparent_from_context()` to capture the current span
   context. This ensures events raised during synchronous command handler
   execution inherit the handler's span context.

**Extraction (incoming messages):**

3. **Command processing** (`CommandProcessor.process()`) and **engine
   message handling** (`Engine.handle_message()`) -- call
   `extract_context_from_traceparent()` to convert the incoming
   `TraceParent` value object back to an OTEL `Context`, passed as the
   `context=` parameter to `start_as_current_span()`. This makes the
   new span a child of the incoming trace.

The bridge uses OTEL's standard `propagate.inject()` and
`propagate.extract()` with W3C `traceparent` format, matching the format
that Protean's `TraceParent` value object already uses. When OTEL is not
installed, both helpers return `None` and the traceparent fields are
simply not populated -- no trace, no overhead, no errors.

A supporting fix was required: `BaseCommand._build_metadata()` previously
discarded headers that contained only a `traceparent` (it required `type`
or `id` to be present). This was corrected to preserve headers with any
meaningful content.

### Part 4: Metrics

A fixed set of metric instruments is defined in the `DomainMetrics` class,
created lazily per domain via `get_domain_metrics(domain)`:

**Counters:** `protean.command.processed`, `protean.handler.invocations`,
`protean.uow.commits`, `protean.outbox.published`, `protean.outbox.failed`

**Histograms:** `protean.command.duration`, `protean.handler.duration`,
`protean.uow.events_per_commit`, `protean.outbox.latency`

Dimensional attributes (e.g., `command_type`, `handler_name`, `status`)
are passed at recording time, not at instrument creation time.

The Observatory's `/metrics` endpoint converges with OTEL: when OTEL is
installed, infrastructure metrics (outbox depth, broker health,
subscription lag) are registered as `ObservableGauge` callbacks on the
OTEL `MeterProvider`, and `get_prometheus_text()` serves the combined
output. When OTEL is not installed, the original hand-rolled Prometheus
exposition is preserved unchanged.

## Consequences

**Positive:**

- Instrumentation code is clean and unconditional. A typical callsite is
  four lines: get tracer, open span, set attributes, handle error. No
  imports from `opentelemetry`, no availability checks.
- The no-op pattern establishes a reusable approach for future optional
  integrations in Protean. Any subsystem that depends on an optional
  package can follow the same gateway + no-op model.
- Full distributed traces flow end-to-end: HTTP request -> command ->
  handler -> event -> outbox -> downstream handler, all linked by W3C
  traceparent propagation.
- Zero overhead when telemetry is disabled: no-ops are trivial objects
  with empty methods; OTEL packages are never imported.
- The `/metrics` endpoint works identically whether OTEL is installed
  or not -- no behavioral change for existing Observatory users.

**Negative:**

- The gateway module is a single point of evolution. Every new OTEL
  feature (e.g., span links, baggage) requires adding a helper to
  `telemetry.py` rather than using OTEL directly. This is by design
  but adds friction.
- The "never import opentelemetry elsewhere" rule is enforced by code
  review, not by tooling. A lint rule (e.g., in 3.5 Architecture
  Fitness Functions) could automate this in the future.
- Trace continuity depends on all three injection/extraction points
  working correctly. If a new message pathway is added without
  traceparent bridging, the trace will break at that boundary.
- The async command path records `status="ok"` and duration at
  enqueue time, even though execution happens later and may fail.
  This is a known trade-off -- the metric reflects "accepted for
  processing", not "completed successfully".

## Alternatives Considered

**Conditional guards at each callsite.** The straightforward approach:
wrap every OTEL call in `if otel_available:`. Rejected because it
scatters the optional dependency boundary across dozens of files, makes
instrumentation code harder to read, and is error-prone (easy to forget
the guard in a new callsite).

**Decorator-based automatic instrumentation.** Automatically wrap
decorated domain elements (e.g., `@domain.command_handler`) with OTEL
spans. Rejected because it provides no control over span attributes,
error recording, or context propagation. The explicit approach gives
each subsystem control over what gets traced and how.

**Single trace system (replace Observatory with OTEL).** Replace the
Redis-backed Observatory entirely with OTEL + an in-process backend.
Rejected because Observatory provides zero-config, real-time SSE-based
tracing for local development. OTEL requires infrastructure (a collector
or backend). The two serve different audiences and coexist at low cost.

**Jaeger/Zipkin-specific integration (instead of OTEL).** Rejected
because OTEL is the industry convergence point. Jaeger and Zipkin both
accept OTLP. Choosing OTEL avoids vendor lock-in and gives users
freedom to pick their backend.

## References

- [OpenTelemetry Python SDK](https://opentelemetry-python.readthedocs.io/)
- [W3C Trace Context specification](https://www.w3.org/TR/trace-context/)
- Epic 6.1: OpenTelemetry Integration (#742)
- ADR-0007: Domain-Scoped OpenTelemetry Providers (companion decision)
