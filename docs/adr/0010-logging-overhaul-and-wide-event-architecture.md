# ADR-0010: Logging Overhaul and Wide Event Architecture

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-23 |
| **Author** | Subhash Bhushan |
| **Epic** | 6.6 Logging Overhaul (#912) |

## Context

Before this epic, Protean had strong logging infrastructure on paper: `structlog>=24.1.0` was a core dependency, `protean.utils.logging.configure_logging()` shipped environment-aware defaults, and Epic 6.5 had wired a `ProteanCorrelationFilter` and `protean_correlation_processor` so that every log record could carry `correlation_id` and `causation_id`. The operational experience lagged the infrastructure in thirteen concrete ways, catalogued in the epic description:

1. The framework did not dogfood its own API — 99 of 103 internal modules used stdlib `logging.getLogger(__name__)` with f-string messages. Only four files (all CLI) used `get_logger()`.
2. Production was silent. Distribution was 44% DEBUG, 21% ERROR, 17% WARNING, 11% INFO, 4% EXCEPTION — an operator running at INFO saw almost nothing.
3. Stack traces were being discarded. `logger.error(str(exc))` at several sites in `unit_of_work.py`, `engine.py`, broker and repository adapters swallowed the traceback on the most important failure paths.
4. Stdlib handlers bypassed the structlog pipeline. `_setup_stdlib_logging` attached a plain `StreamHandler(sys.stdout)` with no formatter, so framework internals emitted plain text while user `get_logger()` code emitted JSON in the same deployment.
5. OpenTelemetry trace context did not reach logs. Epic 6.1 had rich spans but no processor or filter injected `trace_id` / `span_id` into log records, breaking the log↔trace jump in every APM tool.
6. No declarative configuration. `domain.toml` had no `[logging]` section; tuning per-logger levels, redaction, or handlers required writing Python.
7. CLI had only `--debug`. `protean server` lacked `--log-level` / `--log-format` / `--log-config`, and the other CLI commands had no logging setup at all.
8. Sensitive data could leak. `log_method_call` dumped args and kwargs unconditionally with no redaction filter anywhere in the pipeline.
9. Multi-worker logs could interleave. `server/supervisor.py` created per-worker loggers but there was no `QueueHandler` / `QueueListener` pattern, so JSON records from separate processes could corrupt each other at byte boundaries.
10. Auto-configuration was absent. `Domain.init()` did not call `configure_logging()`. A user who forgot it got Python's default (WARNING, no handlers, no structured output) — silent failure of the observability infrastructure.
11. No wide event pattern. Protean knew the aggregate type, events raised, repository operations, and UoW outcome at the handler layer — but none of that context reached logs. Applications were forced to build their own `ContextVar`-based observability systems.
12. No tail sampling. Emitting a wide event per message is expensive at scale, with no mechanism to keep all errors and slow requests while sampling happy-path events.
13. No HTTP-layer wide event. FastAPI applications had no "one event per HTTP request" that correlated with domain-layer wide events.

The epic closed all thirteen gaps across ten PR-sized sub-issues (#913 – #925) plus a documentation rewrite (#920).

### The loggingsucks.com inheritance

The wide event pattern in this epic takes its shape directly from Jamie Brandon's [*Logging Sucks, So Use Wide Events*](https://loggingsucks.com) article. Two of its principles are load-bearing for what Protean built:

- **One rich event per unit of work**, not many thin events per step. Debugging is a join, and a single event with fifty fields beats fifty events with one field each.
- **Query-oriented fields**, not human-readable strings. Fields should be addressable by log aggregators without regex — `status="failed"` and `duration_ms=842` are queryable, `"Handler failed after 842ms"` is not.

Protean's unique advantage — which the article does not cover, because it is framework-agnostic — is that the framework already knows enormous amounts of domain context at handler-execution time: the aggregate type, the events raised, the repository operations, the UoW outcome. The architecture below is about getting that context onto a wide event automatically, so application code never has to build its own `ContextVar`-based observability system just to see what happened in a request.

## Decision

### 1. Keep structlog, keep stdlib — bridge them

We considered migrating the framework wholesale from stdlib `logging.getLogger(__name__)` to structlog's `get_logger()` — either by mass-editing every internal module or by swapping both for a different library (`loguru`). We rejected both. `structlog` is already a core dependency and integrates cleanly with stdlib via `ProcessorFormatter` and `LoggerFactory`; swapping libraries would be gratuitous churn with no user benefit. And mass-editing 99 modules would introduce a hard `structlog` dependency in the framework internals and produce a massive diff that would be review-prohibitive.

The chosen path is a **pipeline bridge**. `_setup_stdlib_logging` in `src/protean/utils/logging.py` installs a `structlog.stdlib.ProcessorFormatter` on every stdlib handler (console + rotating file). Stdlib `LogRecord` objects flow through the same shared processor chain as structlog events via the formatter's `foreign_pre_chain`, and both converge at a single renderer — `JSONRenderer` in production and staging, `ConsoleRenderer` with Rich tracebacks in development. The result: the same output shape regardless of whether a call site uses `logging.getLogger()` or `get_logger()`, with a small, contained diff.

Two tactical refactors shipped alongside the bridge. First, `logger.error(str(exc))` was converted to `logger.exception(...)` at the canonical stack-trace-lost sites — `unit_of_work.py`, `engine.py`, `outbox_processor.py`, and all adapter files. Second, the top ~50 hot-path log sites (engine lifecycle, outbox processing, subscription lifecycle, UoW commit/rollback, broker publish, repository errors) were converted from f-strings to keyword-argument structured events with snake_case dotted names (`outbox.published`, `subscription.started`, `uow.commit_failed`). The remaining ~435 f-string DEBUG calls were left alone — the `ProcessorFormatter` renders them correctly without edits, and mass-editing them would bloat the diff without producing user-visible improvement. The dogfooding problem (99 of 103 modules using stdlib loggers) was solved by pipeline uniformity, not by rewriting every import.

### 2. Wide events are the access log — one per unit of work

The first architectural question was *where* to emit the wide event. Candidates were: (a) a middleware wrapping the handler dispatch path, (b) a decorator applied per handler, or (c) a dedicated logger called from the handler-execution layer.

We chose **(c) dedicated logger**. `protean.access` is emitted from the `access_log_handler` context manager in `src/protean/utils/logging.py`, which wraps every command / event / query / projector dispatch inside the handler mixin. One structured event per handled message. This mirrors how Django emits `django.request` and how uvicorn emits `uvicorn.access` — operators already know how to route, filter, and sample loggers by name.

Middleware was rejected because the framework has no single middleware chain for handler dispatch. A decorator was rejected because it would require every handler author to remember to apply it — the framework has enough context at the dispatch layer to be invisible about this, so the point is to be invisible about it.

The wide event carries sixteen framework-populated fields: `kind`, `message_type`, `message_id`, `aggregate`, `aggregate_id`, `events_raised`, `events_raised_count`, `repo_operations`, `uow_outcome`, `handler`, `duration_ms`, `status`, `error_type`, `error_message`, `correlation_id`, `causation_id`.

**Slow-handler detection is framework-level, not per-handler.** A related design question was how operators should declare "slow". A per-handler decorator (`@slow_threshold(ms=200)`) was rejected because slow is a deployment-environment concern, not a domain-modelling one, and the same handler can be fast in one environment and slow in another. The single framework knob `[logging].slow_handler_threshold_ms` (default 500 ms) applies uniformly; when a handler exceeds it, the wide event's `status` becomes `"slow"` and a separate `protean.perf.slow_handler` WARNING is also emitted so operators can route slow-handler alerts independently of the access log. Per-handler overrides are deferred until concrete demand emerges.

### 3. `bind_event_context()` uses structlog contextvars — not a new primitive

An earlier design sketch proposed a purpose-built `ContextVar[WideEvent]` that handlers would mutate to add application-specific fields. We rejected it. Structlog already exposes `structlog.contextvars.bind_contextvars()`, which is async-safe, plays correctly with `await` boundaries, and is what user code would already be using if it called `add_context()`. Introducing a parallel primitive would double the concurrency surface area for no gain.

`bind_event_context(**kwargs)` calls `structlog.contextvars.bind_contextvars(**kwargs)`. At handler exit, `_emit_wide_event` reads the bound contextvars via `structlog.contextvars.get_contextvars()` and merges them into the event dict, giving application-specific fields alongside the framework fields. Framework-reserved keys (`kind`, `handler`, `status`, etc.) cannot be overwritten — `_emit_wide_event` strips any app field whose name collides with a framework field or a stdlib `LogRecord` attribute.

The `access_log_handler` context manager snapshots and clears the outer context at entry and restores it at exit, so each handler invocation starts with a clean slate and outer bindings (per-request context from `add_context()`) are preserved for surrounding code.

### 4. Two layers of wide events — same correlation_id, independent routing

A single unified access log covering both HTTP requests and domain messages was considered and rejected. The two layers answer different operational questions:

- `protean.access` answers "what did my handler do" — aggregate-level domain context, events raised, repo operations, UoW outcome.
- `protean.access.http` answers "what happened at the HTTP boundary" — method, path, status, duration, commands dispatched, request envelope.

Operators need to route and sample them independently. An HTTP request that dispatches three commands produces one `protean.access.http` event and three `protean.access` events. They share the same `correlation_id` so an operator can pull the full thread for a request from a log aggregator with a single query.

The implementation has one subtle constraint: Starlette runs endpoint functions in a *child asyncio task*, and contextvars bound in that task are not observable from the middleware's parent task where the HTTP wide event is emitted. So `bind_event_context()` *dual-writes*: it binds the kwargs via structlog contextvars (picked up by the domain-layer wide event) and also mirrors them onto `g._http_wide_event_extras`, a dict the `DomainContextMiddleware` installs before `await call_next` and reads after. Without this mirror, `bind_event_context(user_id=...)` called from a FastAPI endpoint would reach the domain-layer wide event but never the HTTP wide event — silently broken.

The nesting of logger names is deliberate: `protean.access.http` is a child of `protean.access` in Python's logger hierarchy, so a filter attached to `protean.access` (like the tail sampling filter) automatically applies to both. This is why the tail sampling filter's namespace match uses `startswith("protean.access.")` rather than an exact match.

### 5. Tail sampling — opt-in, rule-ordered, annotated

At scale, emitting a wide event per message is expensive. But head sampling (decide at start of request whether to log it) loses the most valuable events — errors and slow requests — at exactly the moments you need them. We chose **tail sampling**: the decision happens after the unit of work completes, when the framework knows `status`, `duration_ms`, and `message_type`. Errors and slow requests are always kept; the remainder is sampled at a configurable rate.

The rule order is important: `always_keep_errors` → `always_keep_slow` → `critical_streams` (glob match on `message_type`) → random sampling at `default_rate`. First match wins. Every kept event carries `sampling_decision`, `sampling_rule`, and `sampling_rate` so log aggregators can compute accurate throughput from sampled data (`actual_count = sampled_count / sampling_rate`). Without this metadata, sampled logs silently lie about throughput.

Sampling is implemented as both a structlog processor (`TailSamplingProcessor`) and a stdlib filter (`TailSamplingFilter`). Both are needed because the primary wide event flows through the stdlib `access_logger` (so the stdlib filter runs), but direct `structlog.get_logger("protean.access")` call sites go through the structlog chain. The processor short-circuits when `sampling_decision` is already present in the event dict — a safeguard against the double-sampling that would otherwise happen when a stdlib record is rendered through `ProcessorFormatter.foreign_pre_chain`: the filter would keep it, annotate the record, and then the processor would draw `random()` again and could override the filter's decision.

Sampling is **opt-in via `[logging.sampling].enabled`, disabled by default**. Operators who do not know about sampling retain full visibility. When they hit scale limits, they enable it with one line in `domain.toml`.

Sampling runs *before* redaction in the processor chain so rules can read unredacted fields (`status`, `message_type`) — redaction then masks the fields of the events that survive. Getting that ordering wrong would either mask the fields sampling needs to route or fail to mask surviving events.

### 6. Auto-configuration on `Domain.init()` — with three escape hatches

Django calls `dictConfig` during `Django.setup()`. Protean did not — the previous `Domain.init()` required users to remember to call `configure_logging()`, and "silent failure of observability infrastructure" was the inevitable result.

`Domain.init()` now calls `self.configure_logging()` automatically via `_auto_configure_logging()` on the `Domain` class. Three guardrails prevent surprises:

1. **Environment escape hatch**: `PROTEAN_NO_AUTO_LOGGING=1` disables auto-configuration entirely. For users who want full manual control.
2. **Idempotency guard**: if the root logger already has handlers, auto-configuration is skipped with a `DEBUG` message. This respects user or framework-level setup that happened before `Domain.init()` — for example, a test fixture that configured logging for a specific test.
3. **Non-fatal degradation**: auto-configuration is wrapped in a try/except so logging misconfiguration never breaks `Domain.init()`. The framework emits a warning to stderr and continues.

Configuration precedence is: explicit `Domain.configure_logging(**kwargs)` > `PROTEAN_LOG_LEVEL` / `PROTEAN_LOG_FORMAT` env vars > `domain.toml [logging]` section > environment-based defaults (`_ENV_LEVEL_MAP`). The precedence chain is the same one that `configure_logging()` already applied for the `level` parameter before this epic — extending it to the whole config surface is natural.

### 7. OpenTelemetry trace context — opt-in via `telemetry.enabled`

Epic 6.1 added OTel spans across the framework; Epic 6.5 added correlation IDs to log records. Epic 6.6 closes the gap between the two: when `telemetry.enabled=True`, `Domain.configure_logging()` installs an `OTelTraceContextFilter` on the root logger and appends a `protean_otel_processor` to the structlog pipeline. Both read the active span via `opentelemetry.trace.get_current_span()` and inject `trace_id`, `span_id`, and `trace_flags` into every log record. Outside a valid span, or when the `opentelemetry` extra is not installed, the fields default to empty strings / `0`.

The processor is opt-in *per the existing telemetry gate*, not behind a new config flag. If the user has opted into OTel, they get log↔trace correlation too — no extra decision required. If they have not, the structlog chain does not even pay the cost of a no-op processor on every log call, because the processor is never appended.

OTel imports happen lazily on first call to `_get_otel_trace_context`, cached in module-level sentinels so the hot path is a pure attribute lookup after the first call. Merely importing `protean.integrations.logging` does not trigger an `opentelemetry` import.

### 8. Redaction — processor/filter level, unioned defaults, depth-bounded

Redaction at call sites was considered and rejected within the first few minutes of design — it is the one pattern that never survives contact with the real world. Any new log call that forgets to redact becomes a data leak, and reviewers cannot reliably catch them.

Redaction runs at the **pipeline level** — a stdlib `Filter` (`ProteanRedactionFilter`) and a structlog processor (`make_redaction_processor` / `protean_redaction_processor`) mask values whose keys match the configured list, regardless of where the value originated. Defaults (`password`, `token`, `secret`, `api_key`, `authorization`, `cookie`, `session`, `csrf`) are **unioned** with the operator-supplied list, not substituted. Operators cannot accidentally stop masking a core field by supplying their own list — a security invariant we explicitly want enforced by the framework.

Matching is case-insensitive. Recursion into `dict` / `list` / `tuple` is bounded to `_MAX_REDACT_DEPTH=5` levels. Pathological nested payloads cannot stall logging. Redaction is a best-effort hygiene filter, not a security boundary — structured sensitive data that a specific application needs to handle still belongs in secrets management, not in log fields.

The redaction processor is **appended** to the structlog chain so it runs last, after all caller-supplied processors (correlation, OTel, tail sampling, custom enrichment). Any mention of a redacted field name in any log event — no matter where it was added — is masked before the renderer sees it. The ordering is not optional: if redaction ran earlier, a subsequent processor could add a sensitive field and bypass the mask.

`log_method_call` now inherits the masking transparently because its DEBUG records flow through the same pipeline — no per-decorator flag needed.

### 9. Multi-worker log queue — single-process unchanged

Multi-process log interleaving is a real operational problem: separate `protean server` worker processes writing JSON records to the same stdout can corrupt each other at byte boundaries (longer than OS `PIPE_BUF`, which is 4 KB on Linux and 512 bytes on some BSDs). A single unparseable JSON line breaks the log aggregator's ingestion for the whole line.

`protean server --workers N` (with `N > 1`) now installs a `QueueHandler` on each worker process and a `QueueListener` on the supervisor. Workers push `LogRecord` objects onto a `multiprocessing.Queue`; the supervisor drains the queue and hands records to its own handlers for final rendering. The listener is stopped in a `finally` block on shutdown so records pending in the queue are drained before process exit.

**Single-worker mode is unchanged** — no queue overhead, no extra process, no behavioural change. The queue pattern only engages when the concurrency pattern requires it, following the principle of paying only for what you use.

### 10. `protean.security` logger — SIEM feed, not a bucket for every error

Operators need a dedicated channel for invariant violations, validation failures that cross a domain boundary, and invalid operation / state exceptions — distinct from the general access log — so they can route these to a SIEM or alerting pipeline without sampling, tail-keeping rules, or format changes interfering.

`protean.security` emits WARNING events: `invariant_failed`, `validation_failed`, `invalid_operation`, `invalid_state`. These constants are exposed as module-level `SECURITY_EVENT_*` values in `src/protean/integrations/logging/__init__.py` so call sites cannot drift typographically from what operators query in their aggregators.

The channel is deliberately **narrow**: internal validation errors that a handler catches and retries never reach it. Only events that crossed a domain boundary and were not recovered — the ones an operator actually wants to see — are emitted. If every validation error emitted here, the channel would be noise by week two.

### 11. CLI control surface — deprecation pathway for `--debug`

Every CLI subcommand (`server`, `test`, `shell`, `projection`, `snapshot`, `observatory`, `check`, `dlq`, `events`) now accepts global `--log-level`, `--log-format`, and `--log-config` flags inherited from the Typer callback. Precedence: `--log-config` (dictConfig) > `--log-level` / `--log-format` > `Domain.init()` auto-configuration.

`--debug` on `server` and `observatory` is now a **Tier 1 surface-level break** per ADR-0004. The flag still works — it delegates to `configure_logging(level="DEBUG")` — but emits a `DeprecationWarning` pointing operators to `--log-level DEBUG`, with removal in v0.17.0. This is the minimum survival of two minor versions mandated by ADR-0004. The rest of the epic introduces new APIs and config keys but does not rename or remove existing ones — all other changes are strictly additive.

Every CLI command wraps its main body in `cli_exception_handler` so unhandled exceptions are logged with a structured event *before* propagating and killing the process. Without this, a traceback to stderr was the only artefact — now an operator running under a log aggregator sees the failure in the same structured stream as everything else.

### 12. Slow SQL query detection — adapter-level, not framework-level

A sibling concern to slow-handler detection is slow-query detection. We deliberately pushed it to the adapter rather than the framework. The SQLAlchemy repository adapter emits `protean.adapters.repository.sqlalchemy.slow_query` WARNING events when a query exceeds `[logging].slow_query_threshold_ms` (default 100 ms), with the query text truncated to `slow_query_truncate_chars` characters.

The reason this lives in the adapter is that slow-query semantics depend on the driver: SQLAlchemy exposes a native `before_cursor_execute` / `after_cursor_execute` hook that makes the measurement trivial, while Elasticsearch, memory, and any future adapters would each need their own instrumentation. The framework defines the config surface (`slow_query_threshold_ms`, `slow_query_truncate_chars`) and the logger-name convention (`protean.adapters.repository.<adapter>.slow_query`); each adapter wires its own detection. This mirrors the Ports & Adapters split established elsewhere in the framework: the port defines the contract, the adapter owns the driver-specific machinery.

## Consequences

**Positive:**

- Operators running `protean server` in production now see informative JSON-structured wide events that answer debugging questions without grep-across-lines investigation. One event per unit of work, sixteen framework-populated fields, application-specific enrichment via `bind_event_context()`.
- Log↔trace correlation is automatic when `telemetry.enabled=True`. An operator debugging a slow request in Grafana/Tempo can pivot directly from a span to the log event and back.
- All framework log records carry `correlation_id`, `causation_id`, and (when OTel is active) `trace_id` / `span_id` / `trace_flags` — without any application code change.
- Sensitive data cannot leak through logs once redaction is configured. Operators cannot weaken the defaults by supplying their own list — the union semantics enforce a floor.
- Multi-worker deployments no longer interleave JSON records at byte boundaries.
- `Domain.init()` auto-configures logging, so a developer who never thinks about logging still gets sensible defaults.
- Tail sampling lets operators control wide-event cost at scale without losing errors and slow requests — the most valuable events are always kept.
- FastAPI applications get HTTP wide events for free, correlated with domain-layer wide events by `correlation_id`, with `X-Request-ID` echoed back on every response.

**Negative:**

- The framework now has two layers of wide events (`protean.access`, `protean.access.http`) that must be kept in sync. Adding a field to one means deciding whether it belongs in the other; drift is a real risk.
- Structlog contextvar semantics leak into the API contract of `bind_event_context`. Callers in Starlette's child task model need to understand that contextvar bindings from an endpoint do not automatically reach the middleware — the dual-write to `g._http_wide_event_extras` is a workaround, not a solution. Future frameworks with similar child-task semantics will need equivalent shims.
- Redaction is a best-effort filter, not a security boundary. Deeply nested sensitive data beyond five levels of nesting is not masked. Operators who need stronger guarantees must still avoid logging sensitive structured payloads in the first place.
- `bind_event_context()` is silent when called outside a handler — it binds to the current contextvars but those bindings will be cleared when the next handler starts. Developers can be surprised that a call outside a handler had no effect on any visible event.
- Tail sampling must be configured carefully: an aggressive `default_rate` (e.g. 0.001) combined with an operator who has not set `always_keep_slow=True` will quietly drop the events that matter most. The defaults (always keep errors and slow) are the only sensible defaults; we did not expose them as defaults-off.
- The `ProcessorFormatter` bridge means stdlib log calls now run through the structlog processor chain. On a very hot debug path, this is more work per call than the old plain formatter did. In practice, production deployments run at INFO and the DEBUG paths are not emitted, so the cost is paid only when debug is explicitly enabled.

## Alternatives Considered

**Mass migration to structlog `get_logger()` in framework internals.** Rejected because the pipeline bridge achieves the same output uniformity with a ~99-module-smaller diff, and because introducing a hard structlog dependency at every framework callsite constrains future library choices.

**Swap structlog for loguru.** Rejected. `loguru` is a single-line-setup library that optimises for developer convenience in small scripts; structlog optimises for composable processor chains in production systems. Protean's needs (pipeline integration with stdlib, processor-level redaction, contextvar-based enrichment, OTel integration, tail sampling) map cleanly onto structlog's model and do not map cleanly onto loguru's.

**Custom `ContextVar[WideEvent]` primitive for `bind_event_context`.** Rejected because structlog's contextvars already solve the problem. Every new concurrency primitive is a potential source of async-safety bugs; reusing the one that is already vetted in production is strictly safer.

**Head sampling instead of tail sampling.** Rejected. Head sampling decides whether to log at the start of a request, which loses exactly the events (errors, slow requests) that operators most want to keep. Tail sampling pays a small cost — the event dict is assembled regardless — in exchange for never losing the signal.

**Decorator-based per-handler wide event instrumentation.** Rejected. A decorator would require every handler author to remember to apply it, which defeats the framework's ability to be invisible about observability. The access log emits from the handler-execution layer so no handler author opts in or out.

**Middleware for access log (instead of dedicated logger).** Rejected because the framework has no single middleware chain covering command handlers, event handlers, query handlers, and projectors. A dedicated logger emitted from the handler mixin reaches all four paths from one location.

**Email-on-error handler** (Django's `AdminEmailHandler`). Rejected on scope. Paging belongs in the alerting layer, not the logging layer. Operators route `level=ERROR` events from their log aggregator to PagerDuty or Slack; the framework should not re-invent that.

**Observatory log viewer**. Rejected on scope. Observatory's value is traces and events — logs belong in log aggregators (Loki, Elasticsearch, CloudWatch). Fighting log vendors is out of scope.

**Single unified `protean.access` logger for HTTP and domain events.** Considered and rejected because operators need independent routing and sampling rules for the two layers. A user-agent 4xx rate limit hit and a domain-level handler failure are different problems with different operational responses; unifying them behind one logger name would force operators to re-split them with regex at ingestion time.

**Per-call-site redaction flags.** Rejected. Any pattern that depends on every new log call remembering to redact will eventually fail, and the failure mode is a data leak. Pipeline-level redaction with unioned defaults is the only approach that stays correct under real-world refactoring.

## References

- Epic 6.6: Logging Overhaul (#912) — design decisions and sub-issue breakdown
- Sub-issue #913 — Structured logging baseline and stdlib→structlog pipeline bridge
- Sub-issue #914 — Auto-configuration on `Domain.init()` and `[logging]` config section
- Sub-issue #915 — CLI logging control surface
- Sub-issue #916 — Wide event access log, domain context enrichment, slow-handler detection
- Sub-issue #917 — OpenTelemetry trace context injection
- Sub-issue #918 — Slow SQL query detection in SQLAlchemy repository adapter
- Sub-issue #919 — Sensitive-field redaction, multi-worker log queue, `protean.security` logger
- Sub-issue #924 — Tail sampling for wide events
- Sub-issue #925 — FastAPI HTTP-layer wide event middleware
- Sub-issue #920 — Logging documentation overhaul (guide, reference, concept pages)
- ADR-0004 — Release Workflow and Breaking Change Policy (classification for the `--debug` deprecation)
- ADR-0007 — Domain-Scoped OpenTelemetry Providers (log↔trace correlation precursor)
- ADR-0008 — Centralized Telemetry Gateway and TraceParent Bridging (log↔trace correlation companion)
- [Jamie Brandon, *Logging Sucks, So Use Wide Events*](https://loggingsucks.com) — wide event pattern
