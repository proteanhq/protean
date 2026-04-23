# Logging

This page explains *why* Protean's logging works the way it does. For
task-oriented instructions see the
[Logging guide](../../guides/server/logging.md); for a factual enumeration
of config keys, framework loggers, and event schemas see the
[Logging reference](../../reference/logging.md).

---

## Why structured logs?

The [12-factor](https://12factor.net/logs) treatment of logs as an event
stream has been conventional wisdom for more than a decade, but most
codebases still produce human-formatted strings and call it a day:

```python
# The old way — looks readable, queries like grep
logger.info(f"Refunded ${amount} for order {order_id} because {reason}")
```

When a customer reports a missing refund, you open Loki or Elasticsearch
and search. You don't know whether people wrote `"Refunded"` or
`"Refund issued"` or `"Processing refund"`; you don't know whether the
amount comes before or after the order id; you don't know whether the
reason is free text or a code. Every query is an archaeology dig.

Structured logs invert that:

```python
# The Protean way — event name is stable, fields are queryable
logger.info("payment_refunded", order_id="ord-123", amount=19.99, reason="customer_request")
```

`event=payment_refunded AND reason=customer_request` is a viable query.
`avg(amount) by reason` is a viable aggregation. `count by hour` draws a
time series. Strings are opaque; fields are data.

Protean commits to this pattern throughout — every hot-path event emitted
by the framework uses a stable name and structured fields, and the
`get_logger()` API encourages application code to do the same.

---

## The wide event pattern

Structured logs alone still leave an observability gap: when something
goes wrong inside a handler, you typically have a dozen scattered log
lines — "started processing", "loaded aggregate", "validated input",
"raised event", "saved aggregate", "committed UoW" — and you have to
reconstruct the full story by filtering on `correlation_id`.

The **wide event pattern** replaces that stream of thin events with one
**rich event per unit of work**. Stripe's engineering blog codified this
as the [canonical log line pattern](https://brandur.org/canonical-log-lines):

> We emit one log line for every request our application handles. The
> log line contains every field we might want to query on: request id,
> user id, response time, status code, billing plan, A/B test cohorts,
> and so on.

That one log line answers:

- "Which requests failed in the last 10 minutes?"
- "What's the p99 latency for premium users on the checkout endpoint?"
- "Which feature-flag cohort shows the highest error rate?"

…without joining log lines or re-running the query over a dozen thin events.

### Designing fields for queryability

The practical insight: **choose log fields by asking "what questions will
operators ask at 3 AM?"** not "what is my code doing right now." That
reframes debugging from archaeology — grep for strings until a pattern
emerges — to analytics — run an aggregation on a queryable schema.

Examples of queries wide events enable when the right fields are bound:

- "Show all payment failures for premium users in the last hour grouped
  by error code."
- "What's the p99 handler duration for `PlaceOrder` commands where
  `coupon_applied` is not null?"
- "Which aggregates have the highest `events_raised_count`? (potential
  aggregate design smell.)"
- "Which correlation chains span more than five handlers? (long-running
  flows worth inspecting.)"

If your wide event can answer those questions, you've picked the right
fields. If it can't, you're still doing archaeology.

---

## How Protean builds wide events automatically

No other Python framework can auto-populate domain fields like
`aggregate`, `events_raised`, or `uow_outcome` because no other framework
models those concepts at the framework layer. Protean builds the wide
event from two sources:

- **A framework layer**, always present with no code required — handler
  identity, duration, aggregate, events raised, repository operations,
  UoW outcome, correlation, and (when telemetry is enabled) trace
  context. See the [reference](../../reference/logging.md#proteanaccess)
  for the exhaustive field list.
- **An application layer**, whatever the handler binds via
  `bind_event_context()` — user tier, order total, feature flags, tenant
  plan.

The two layers merge into a single event emitted when the handler
returns. The framework keeps ownership of its fields: application keys
that collide with a framework-reserved name are dropped before emission,
so the meaning of `handler` or `uow_outcome` never depends on what the
caller happened to bind.

---

## Query-oriented field design

When choosing what to `bind_event_context()`, favour fields that:

- **Are queryable dimensions, not free text.** Prefer `user_tier="premium"` to
  `note="premium user doing checkout"`.
- **Are stable.** If a value changes shape every deployment, it's a poor
  aggregation key.
- **Are low enough cardinality to group by, high enough to be useful.**
  `tenant_id` is great; `uuid_of_every_request` is not (unless your backend
  handles it — see below).
- **Name the business concept the operator will ask about.**
  `coupon_applied=True` beats `flags.coupon=1` because the former reads
  cleanly in a filter.

Leave out fields that only matter inside the handler itself — those
belong in DEBUG-level thin events, not the wide event.

---

## High-cardinality fields and backend choice

Wide events produce data that legacy log backends struggle with. A single
event carries a request id, a user id, an aggregate id, a correlation id,
possibly a tenant id — every one of them high-cardinality by design,
because they're exactly what an operator filters by.

Syslog-era stores built for low-cardinality tagging don't index these
well; queries over them fall back to full scans. Modern columnar log
stores — Loki with structured metadata, ClickHouse, BigQuery, CloudWatch
Logs Insights, Datadog Log Analytics — handle high cardinality natively.

Protean does not recommend a specific vendor. The heuristic is: if your
logging aggregator makes `filter user_id=X` or `top by aggregate_id`
queries slow, the bottleneck is the backend, not the event shape. Fix
that first before trimming fields out of the wide event.

---

## How Protean's logging differs from Django and FastAPI

| Feature | Django | FastAPI (ASGI + uvicorn) | Protean |
|---------|--------|--------------------------|---------|
| Structured logs by default | No (stdlib messages) | No (uvicorn access log is plain-text) | Yes (`structlog` pipeline on by default) |
| Wide event per request | No | No | Yes (`protean.access`) |
| Domain context in logs | Manual | Manual | Auto (aggregate, events, UoW outcome, correlation) |
| Correlation ID in logs | Manual | Manual | Auto |
| OpenTelemetry trace context in logs | Manual | Manual | Auto when `telemetry.enabled = true` |
| `dictConfig` support | Yes | Yes | Yes (via `--log-config` or `dict_config=`) |
| Redaction | Manual | Manual | Built-in processor with default keys |
| Multi-worker hygiene | N/A (single process) | Manual | Built-in `QueueHandler` / `QueueListener` in `--workers N` mode |

The gap Protean closes is the domain-aware one: aggregate, events raised,
UoW outcome. No other Python framework can populate those automatically
because no other framework models them. The commodity features
(structured logs, dictConfig, correlation filter) are also on by default —
where Django and FastAPI leave them to the operator.

---

## The four sources of context

Every resolved setting comes from one of four places. The precedence,
from highest to lowest:

1. **Explicit keyword arguments** to `Domain.configure_logging()` or
   `configure_logging()`. Callers always win.
2. **Environment variables** (`PROTEAN_LOG_LEVEL`, `PROTEAN_ENV`). Useful
   for container orchestration.
3. **`domain.toml [logging]` section.** The declarative surface operators
   tune during deployment.
4. **Environment-based defaults.** `PROTEAN_ENV=production` picks INFO +
   JSON; `development` picks DEBUG + console; `test` picks WARNING +
   console.

This precedence matches every other resolvable setting in Protean
(`server`, `telemetry`, `databases`) so operators don't need to memorize
a per-subsystem rule. It also means the right answer to "what will my
deployment see?" is always: check the kwargs, then the env vars, then
`domain.toml`, then the environment.

---

## How correlation propagates to logs

The `ProteanCorrelationFilter` (stdlib) and `protean_correlation_processor`
(structlog) read `g.message_in_context.metadata.domain.correlation_id`
first, then fall back to `g.correlation_id`. The fallback is the
documented extension point for HTTP middleware, CLI commands, and
background jobs that tag context before any domain message exists.

Both are safe no-ops outside a domain context: they return `""` for both
fields so formatters referencing `%(correlation_id)s` never raise
`KeyError`. That no-op semantics is the reason Protean can attach the
filter to the root logger unconditionally — it costs one attribute set
per record and changes nothing about the output shape when context is
absent.

For the full correlation story across HTTP, events, subscribers, and
OTel spans, see
[Correlation and Causation IDs](../../guides/observability/correlation-and-causation.md).

---

## How trace context reaches logs

OpenTelemetry trace context (`trace_id`, `span_id`, `trace_flags`) is
injected by `OTelTraceContextFilter` and `protean_otel_processor`. Both
are installed only when `telemetry.enabled = true` — when telemetry is
disabled, the structlog chain has one fewer processor and the root
logger has one fewer filter, so the hot path pays zero cost.

The processor lazily resolves OpenTelemetry symbols on first access and
caches the result. If `opentelemetry` is not installed (the `telemetry`
extra is optional), the processor emits empty values and never retries
the import.

This design enables the **log ↔ trace jump** in every APM tool: click a
trace in Jaeger or Datadog, copy its `trace_id`, paste it into Loki or
Elasticsearch, see every log record from the same request. Without the
`trace_id` field on log records, that jump requires custom middleware.

See [ADR-0007](../../adr/0007-domain-scoped-opentelemetry-providers.md)
and [ADR-0008](../../adr/0008-centralized-telemetry-gateway-and-traceparent-bridging.md)
for the OTel architecture this layer builds on.

---

## Why redaction is processor-based

Call-site redaction — "be careful what you log!" — never survives contact
with the real world. Someone, somewhere, forgets. A stacktrace inlines a
request body. A new feature logs more than its predecessor. A
well-meaning debug line ships to production.

The only pattern that survives is **redaction as a pipeline stage**: any
mention of a sensitive key name in any log event is masked before
rendering, regardless of where in the pipeline the value was introduced.
Protean's redaction processor runs **last** in the structlog pipeline —
after every caller-supplied processor — so operator-supplied processors
cannot smuggle sensitive values past it, whether intentionally or by
accident.

The redact list is **unioned** with the built-in defaults, not replaced.
Operators can only widen the list — never narrow it. You cannot turn off
`password` masking by supplying your own list.

Redaction is a hygiene filter, not a security boundary: don't store
secrets where their redaction is the last line of defence. Authentication
tokens belong in a vault, not a best-effort log filter.

---

## Multi-worker hygiene

stdout writes from separate processes are not atomic beyond `PIPE_BUF`
bytes — typically 4096 on Linux, 512 on BSD. A structured JSON log
record easily exceeds either. Without coordination, concurrent worker
output interleaves mid-record, and the resulting lines are unparseable.

`protean server --workers N` (with `N > 1`) solves this the way Python's
stdlib recommends: each worker installs a `QueueHandler` as its sole
root handler; the supervisor runs a `QueueListener` that drains the
queue and forwards records to the supervisor's real handlers. Records
cross the process boundary through a `multiprocessing.Queue`, which
preserves record integrity.

The listener is stopped in a `finally` block on shutdown so buffered
records are flushed before the supervisor exits. Single-worker mode is
unchanged — no queue overhead.

---

## Two layers of wide events

Protean emits wide events at the **handler** layer: one event per
handled command, event, query, or projector invocation, on the
`protean.access` logger.

For applications fronted by FastAPI, the HTTP request is the outermost
unit of work, which may trigger zero, one, or several command or query
dispatches. The wide event at the handler layer captures each dispatched
domain operation; the HTTP envelope is captured separately by FastAPI's
own middleware layer (see [FastAPI Integration](../../guides/fastapi/index.md)).

All layers share `correlation_id`, so operators can query `correlation_id = X`
and see the HTTP envelope plus every domain operation it triggered in a
single result set.

---

## What Protean deliberately does not do

Some capabilities that adjacent frameworks ship with are out of scope for
Protean's logging:

- **Email-on-error handlers.** Django's `AdminEmailHandler` is historical
  baggage; paging belongs in an alerting layer (PagerDuty, Opsgenie,
  Alertmanager) reading from the log backend, not a handler buried in
  the logging library.
- **An Observatory log viewer.** Logs belong in log aggregators. The
  Observatory's value is live traces and event timelines — fighting
  Loki, Elasticsearch, and Datadog on their home turf is a losing
  strategy.
- **PII heuristics.** Automatic PII detection is a research problem; the
  current state of the art is too flaky to enable by default without
  false positives that mask real signal. Operators explicitly list the
  keys they care about via `[logging].redact`.
- **Audit log persistence.** Domain events already capture the
  append-only history of what happened. The logging layer is for
  debugging and observability, not business audit trails.

Keeping these out of scope is deliberate. A smaller, coherent logging
story serves operators better than a large one that duplicates
downstream tools.
