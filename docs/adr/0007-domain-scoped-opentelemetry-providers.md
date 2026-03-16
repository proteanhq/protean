# ADR-0007: Domain-Scoped OpenTelemetry Providers

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-03-16 |
| **Author** | Subhash Bhushan |
| **Epic** | 6.1 OpenTelemetry Integration (#742) |

## Context

Protean needed production-grade observability -- distributed tracing and
metrics -- to support ops teams shipping telemetry to backends like
Grafana, Datadog, and Jaeger. OpenTelemetry (OTEL) was the natural choice:
it is vendor-agnostic, widely adopted, and provides the W3C TraceContext
propagation that Protean's `TraceParent` value object already uses.

OTEL's recommended usage pattern is to register a single global
`TracerProvider` and `MeterProvider` at process startup via
`trace.set_tracer_provider()` and `metrics.set_meter_provider()`, then
retrieve them anywhere with `trace.get_tracer()`. This works well for
conventional applications that have exactly one telemetry configuration
per process.

Protean's `Domain` class, however, is designed to be instantiated multiple
times in the same process -- most commonly in tests, where each test case
may create its own `Domain(name="Test")` with different configuration.
The OTEL global registration model creates three problems in this context:

1. **Single-assignment semantics.** OTEL globals are write-once: the first
   call to `set_tracer_provider()` wins, and subsequent calls are silently
   ignored (or log a warning). A second domain in the same process cannot
   override the provider with its own configuration.

2. **Shutdown leaves broken globals.** Calling `shutdown()` on the global
   provider puts it into a terminal state. Any spans created afterward are
   silently dropped. In tests, where domains are created, activated, and
   shut down repeatedly, this means only the first test gets real spans.

3. **No per-domain configuration.** Different domains may need different
   service names, exporters, or resource attributes. A single global
   provider cannot express this.

Protean also already had an existing observability system -- the
**Observatory** -- which provides zero-config, real-time tracing for
developers running `protean server` locally. Observatory uses Redis
Streams and SSE, producing flat `MessageTrace` events. OTEL needed to
coexist with Observatory without replacing it: Observatory serves
developers; OTEL serves ops teams. The two systems share instrumentation
callsites but have independent emission paths, connected only at the
`/metrics` endpoint where OTEL's `PrometheusMetricReader` takes over
when available.

## Decision

We store `TracerProvider` and `MeterProvider` as attributes on the
`Domain` instance, never setting OTEL globals. All access goes through
domain-scoped helpers:

```python
# In application code -- always safe, always returns something usable
tracer = domain.tracer  # lazy property, triggers init on first access
meter = domain.meter

# Under the hood (src/protean/utils/telemetry.py)
def get_tracer(domain, name="protean"):
    provider = getattr(domain, "_otel_tracer_provider", None)
    if provider is None:
        return _NoOpTracer()
    return provider.get_tracer(name)
```

Providers are created during `init_telemetry(domain)`, which is called
lazily on first access to `domain.tracer` or `domain.meter`. A sentinel
flag (`_otel_init_attempted`) prevents repeated initialization attempts.
`shutdown_telemetry(domain)` flushes and destroys the providers, then
resets the sentinel so a new initialization cycle is possible -- critical
for test isolation.

The `Domain` class exposes two lazy properties:

- `domain.tracer` -- returns a configured OTEL `Tracer` or a `_NoOpTracer`
- `domain.meter` -- returns a configured OTEL `Meter` or a `_NoOpMeter`

Both use deferred imports so the `opentelemetry` package is never loaded
unless telemetry is actually accessed.

Telemetry is **disabled by default** (`telemetry.enabled: False` in
domain config) and all OTEL packages are optional extras
(`pip install protean[telemetry]`). When disabled or when packages are
absent, all public functions return lightweight no-op objects that
implement the minimal OTEL interface, so instrumentation code never
needs conditional guards.

## Consequences

**Positive:**

- Each domain instance owns its telemetry lifecycle. Tests create isolated
  domains with `InMemorySpanExporter` and assert on spans without
  cross-test contamination.
- Multiple domains in the same process (e.g., a multi-bounded-context
  deployment) can have independent service names, exporters, and resource
  attributes.
- Clean shutdown/re-init cycles work correctly -- no "zombie provider"
  problem where a shut-down global silently drops spans.
- Observatory and OTEL coexist cleanly at instrumentation callsites.
  The `/metrics` endpoint serves OTEL Prometheus exposition when available,
  falling back to the hand-rolled implementation when not.

**Negative:**

- Diverges from OTEL's documented best practice. Contributors familiar
  with OTEL will initially reach for `trace.get_tracer()` (the global)
  and need to learn the domain-scoped pattern.
- Every instrumented callsite must have access to the `Domain` instance
  (typically via `current_domain` context or direct reference) to obtain
  a tracer or meter.
- Third-party OTEL auto-instrumentation libraries that expect global
  providers (e.g., `opentelemetry-instrumentation-requests`) will not
  automatically participate in Protean's domain-scoped traces. Manual
  bridging would be needed.

## Alternatives Considered

**Global providers (OTEL default).** Rejected because of the
single-assignment, broken-shutdown, and no-per-domain-config problems
described in Context. These are fundamental to OTEL's design and
unlikely to change upstream.

**Per-thread providers.** Would solve test isolation for single-threaded
test runners but not for async or multi-domain production scenarios.
Also adds complexity without addressing the configuration problem.

**Monkey-patching OTEL globals per test.** Fragile, requires careful
teardown ordering, and breaks if any library caches a reference to the
old provider.

## References

- [OTEL Python SDK: TracerProvider](https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.html)
- [OTEL specification: Global providers are set once](https://opentelemetry.io/docs/specs/otel/trace/api/#get-a-tracer)
- Epic 6.1: OpenTelemetry Integration (#742)
