# ADR-0010: Logging Overhaul and Wide Event Architecture

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-23 |
| **Author** | Subhash Bhushan |
| **Epic** | 6.6 Logging Overhaul (#912) |

## Context

Before this epic, Protean had strong logging infrastructure on paper:
`structlog>=24.1.0` was a core dependency,
`protean.utils.logging.configure_logging()` shipped environment-aware defaults,
and Epic 6.5 had wired a `ProteanCorrelationFilter` and
`protean_correlation_processor` so that every log record could carry
`correlation_id` and `causation_id`. In thirteen concrete ways, catalogued in
the epic description, operators got less from the logs than this infrastructure
could give:

1. The framework did not use its own logging API. Of 103 internal modules, 99
   used stdlib `logging.getLogger(__name__)` with f-string messages. Only four
   files (all CLI) used `get_logger()`.
2. Production logs were nearly empty. Of the framework's log calls, 44% were
   DEBUG, 21% ERROR, 17% WARNING, 11% INFO and 4% EXCEPTION. An operator
   running at INFO saw almost nothing.
3. Stack traces were being discarded. At several sites in `unit_of_work.py`,
   `engine.py`, broker and repository adapters, the framework called
   `logger.error(str(exc))` and dropped the traceback on the most important
   failure paths.
4. Stdlib handlers bypassed the structlog pipeline. `_setup_stdlib_logging`
   attached a plain `StreamHandler(sys.stdout)` with no formatter. As a result,
   framework internals emitted plain text while user `get_logger()` code
   emitted JSON in the same deployment.
5. OpenTelemetry trace context did not reach logs. The tracing epic (Epic 6.1)
   added detailed spans, but no processor or filter injected `trace_id` /
   `span_id` into log records. Without those fields, the log↔trace jump failed
   in every APM tool.
6. No declarative configuration. `domain.toml` had no `[logging]` section; tuning per-logger levels, redaction, or handlers required writing Python.
7. CLI had only `--debug`. `protean server` lacked `--log-level` /
   `--log-format` / `--log-config`. The other CLI commands had no logging setup
   at all.
8. Sensitive data could leak. `log_method_call` dumped args and kwargs unconditionally with no redaction filter anywhere in the pipeline.
9. Multi-worker logs could interleave. `server/supervisor.py` created
   per-worker loggers but had no `QueueHandler` / `QueueListener` pattern.
   Without that pattern, JSON records from separate processes could corrupt
   each other at byte boundaries.
10. Auto-configuration was absent. `Domain.init()` did not call `configure_logging()`. A user who forgot it
    got Python's default (WARNING, no handlers, no structured output), silent
    failure of the observability infrastructure.
11. No wide event pattern. Protean knew the aggregate type, events raised,
    repository operations, and UoW outcome at the handler layer, but none of
    that context reached logs. Applications were forced to build their own
    `ContextVar`-based observability systems.
12. No tail sampling. At scale, a wide event per message is expensive. Protean
    had no mechanism that kept all errors and slow requests and sampled the
    happy-path events.
13. No HTTP-layer wide event. FastAPI applications had no "one event per HTTP request" that correlated with domain-layer wide events.

The epic closed all thirteen gaps across ten PR-sized sub-issues (#913 to #925) plus a documentation rewrite (#920).

### The loggingsucks.com inheritance

The wide event pattern in this epic follows Jamie Brandon's [*Logging Sucks, So
Use Wide Events*](https://loggingsucks.com) article directly. Protean's design
depends on two of the article's principles:

- **One rich event per unit of work**, not many thin events per step. When you
  debug, you join facts about one unit of work. A single event with fifty
  fields serves that join better than fifty events with one field each.
- **Query-oriented fields**, not human-readable strings. Fields should be
  addressable by log aggregators without regex, `status="failed"` and `duration_ms=842` are queryable, `"Handler failed after 842ms"`
  is not.

The article is framework-agnostic, so it does not cover one thing Protean can
add. At handler-execution time, the framework already knows a large amount of
domain context: the aggregate type, the events raised, the repository
operations, the UoW outcome. Protean puts that context onto a wide event
automatically, as the decisions below describe. Application code then never has
to build its own `ContextVar`-based observability system to see what happened
in a request.

## Decision

### 1. Keep structlog, keep stdlib: bridge them

We considered migrating the framework wholesale from stdlib
`logging.getLogger(__name__)` to structlog's `get_logger()`, either by
mass-editing every internal module or by swapping both for a different library
(`loguru`). We rejected both. `structlog` is already a core dependency and
integrates cleanly with stdlib via `ProcessorFormatter` and `LoggerFactory`.
Swapping libraries would mean needless change with no benefit to users.
Mass-editing 99 modules would add a hard `structlog` dependency to the
framework internals. The same edit would produce a diff too large to review.

The chosen path is a **pipeline bridge**. `_setup_stdlib_logging` in
`src/protean/utils/logging.py` installs a `structlog.stdlib.ProcessorFormatter`
on every stdlib handler (console + rotating file). Stdlib `LogRecord` objects
pass through the same shared processor chain as structlog events via the
formatter's `foreign_pre_chain`. Both kinds of record reach a single renderer:
`JSONRenderer` in production and staging, `ConsoleRenderer` with Rich
tracebacks in development. Every call site produces the same output shape,
whether it uses `logging.getLogger()` or `get_logger()`. The diff stays small
and contained.

Two tactical refactors shipped alongside the bridge. First, we converted
`logger.error(str(exc))` to `logger.exception(...)` at the main sites where the
stack trace was lost: `unit_of_work.py`, `engine.py`, `outbox_processor.py`,
and all adapter files. Second, the top ~50 hot-path log sites (engine
lifecycle, outbox processing, subscription lifecycle, UoW commit/rollback,
broker publish, repository errors) were converted from f-strings to
keyword-argument structured events with snake_case dotted names
(`outbox.published`, `subscription.started`, `uow.commit_failed`). The
remaining ~435 f-string DEBUG calls stayed as they were, because the
`ProcessorFormatter` renders them correctly without edits. Mass-editing them
would make the diff larger with no user-visible improvement. The dogfooding
problem (99 of 103 modules using stdlib loggers) was solved by pipeline
uniformity, not by rewriting every import.

### 2. Wide events are the access log: one per unit of work

The first architectural question was *where* to emit the wide event. Candidates were: (a) a middleware wrapping the handler dispatch path, (b) a decorator applied per handler, or (c) a dedicated logger called from the handler-execution layer.

We chose **a dedicated logger** (option (c)). `protean.access` is emitted from
the `access_log_handler` context manager in `src/protean/utils/logging.py`,
which wraps every command / event / query / projector dispatch inside the
handler mixin. One structured event per handled message. Django emits
`django.request` and uvicorn emits `uvicorn.access` in the same way. Operators
already know how to route, filter, and sample loggers by name.

Middleware was rejected because the framework has no single middleware chain
for handler dispatch. A decorator was rejected because it would require every
handler author to remember to apply it. The dispatch layer already has enough
context to emit the wide event without any code in the handler, so Protean
emits it there.

The wide event carries sixteen framework-populated fields: `kind`, `message_type`, `message_id`, `aggregate`, `aggregate_id`, `events_raised`, `events_raised_count`, `repo_operations`, `uow_outcome`, `handler`, `duration_ms`, `status`, `error_type`, `error_message`, `correlation_id`, `causation_id`.

**Slow-handler detection is framework-level, not per-handler.** A related
design question was how operators should declare "slow". We rejected a
per-handler decorator (`@slow_threshold(ms=200)`) because slowness depends on
the deployment environment and has nothing to do with domain modelling. The
same handler can be fast in one environment and slow in another. One framework
setting, `[logging].slow_handler_threshold_ms` (default 500 ms), applies to
every handler. When a handler exceeds it, the wide event's `status` becomes
`"slow"`. The framework also emits a separate `protean.perf.slow_handler`
WARNING, so operators can route slow-handler alerts independently of the access
log. Per-handler overrides are deferred until concrete demand emerges.

### 3. `bind_event_context()` uses structlog contextvars, not a new primitive

In an earlier design sketch, we proposed a purpose-built
`ContextVar[WideEvent]` that handlers would mutate to add application-specific
fields. We rejected it. Structlog already exposes
`structlog.contextvars.bind_contextvars()`. It is async-safe and works
correctly across `await` boundaries. User code that calls `add_context()`
already uses it. A parallel primitive would double the number of concurrency
mechanisms the framework has to keep correct, with no gain.

`bind_event_context(**kwargs)` calls `structlog.contextvars.bind_contextvars(**kwargs)`. At handler exit, `_emit_wide_event` reads the bound contextvars via `structlog.contextvars.get_contextvars()` and
merges them into the event dict, giving application-specific fields alongside
the framework fields. Framework-reserved keys (`kind`, `handler`, `status`, etc.) cannot be
overwritten, `_emit_wide_event` strips any app field whose name collides with a framework
field or a stdlib `LogRecord` attribute.

The `access_log_handler` context manager snapshots and clears the outer context
at entry and restores it at exit. Each handler invocation therefore starts with
an empty context, and surrounding code keeps its outer bindings (per-request
context from `add_context()`).

### 4. Two layers of wide events: same correlation_id, independent routing

A single unified access log covering both HTTP requests and domain messages was considered and rejected. The two layers answer different operational questions:

- `protean.access` answers "what did my handler do", aggregate-level domain context, events
  raised, repo operations, UoW outcome.
- `protean.access.http` answers "what happened at the HTTP boundary", method, path, status,
  duration, commands dispatched, request envelope.

Operators need to route and sample them independently. When an HTTP request
dispatches three commands, Protean produces one `protean.access.http` event and
three `protean.access` events. They share the same `correlation_id`, so an
operator can fetch every event for a request from a log aggregator with a
single query.

The implementation has one subtle constraint. Starlette runs endpoint functions
in a *child asyncio task*. The middleware emits the HTTP wide event from its
parent task, and that parent task cannot see contextvars bound in the child
task. So `bind_event_context()` *dual-writes*: it binds the kwargs via
structlog contextvars, where the domain-layer wide event picks them up. It also
mirrors them onto `g._http_wide_event_extras`, a dict the
`DomainContextMiddleware` installs before `await call_next` and reads after.
Without this mirror, `bind_event_context(user_id=...)` called from a FastAPI
endpoint would reach the domain-layer wide event but never the HTTP wide event,
silently broken.

We nested the logger names on purpose. `protean.access.http` is a child of
`protean.access` in Python's logger hierarchy. A filter attached to
`protean.access` (like the tail sampling filter) therefore applies to both
automatically. This is why the tail sampling filter's namespace match uses
`startswith("protean.access.")` rather than an exact match.

### 5. Tail sampling: opt-in, rule-ordered, annotated

At scale, emitting a wide event per message is expensive. But head sampling
(decide at start of request whether to log it) loses the most valuable events
(errors and slow requests) at exactly the moments you need them. We chose
**tail sampling**. The sampler decides after the unit of work completes, at
which point the framework knows `status`, `duration_ms`, and `message_type`.
The sampler always keeps errors and slow requests. It samples the remaining
events at a configurable rate.

The rule order is important: `always_keep_errors` → `always_keep_slow` →
`critical_streams` (glob match on `message_type`) → random sampling at
`default_rate`. First match wins. Every kept event carries `sampling_decision`,
`sampling_rule`, and `sampling_rate` so log aggregators can compute accurate
throughput from sampled data (`actual_count = sampled_count / sampling_rate`).
Without this metadata, sampled logs understate throughput and give no sign that
they do.

Sampling is implemented as both a structlog processor (`TailSamplingProcessor`)
and a stdlib filter (`TailSamplingFilter`). The primary wide event goes through
the stdlib `access_logger`, so the stdlib filter runs on it. Direct
`structlog.get_logger("protean.access")` call sites go through the structlog
chain instead, so Protean needs both. The processor short-circuits when
`sampling_decision` is already present in the event dict. This guards against
double-sampling when a stdlib record is rendered through
`ProcessorFormatter.foreign_pre_chain`. Without the guard, the filter would
keep the record and annotate it, and then the processor would draw `random()`
again and could override the filter's decision.

Sampling is **opt-in via `[logging.sampling].enabled`, disabled by default**. Operators who do not know about sampling retain full visibility. When they hit scale limits, they enable it with one line in `domain.toml`.

Sampling runs *before* redaction in the processor chain so rules can read
unredacted fields (`status`, `message_type`). Redaction then masks the fields
of the events that survive. With the order reversed, the chain would either
mask the fields that sampling needs to route or fail to mask the events that
survive.

### 6. Auto-configuration on `Domain.init()`: with three escape hatches

Django calls `dictConfig` during `Django.setup()`. Protean did not. The
previous `Domain.init()` required users to remember to call
`configure_logging()`, and the inevitable result was "silent failure of
observability infrastructure".

`Domain.init()` now calls `self.configure_logging()` automatically via
`_auto_configure_logging()` on the `Domain` class. Three safeguards stop the
automatic setup from surprising you:

1. **Turn it off with an environment variable**: `PROTEAN_NO_AUTO_LOGGING=1`
   disables auto-configuration entirely. For users who want full manual
   control.
2. **Skip setup that already exists (idempotency guard)**: If the root logger
   already has handlers, auto-configuration is skipped with a `DEBUG` message.
   This keeps any user or framework-level setup done before `Domain.init()`.
   One example is a test fixture that configured logging for a specific test.
3. **Never break `Domain.init()` (non-fatal degradation)**: Auto-configuration
   is wrapped in a try/except so logging misconfiguration never breaks
   `Domain.init()`. The framework emits a warning to stderr and continues.

Configuration precedence is: explicit `Domain.configure_logging(**kwargs)` >
`PROTEAN_LOG_LEVEL` / `PROTEAN_LOG_FORMAT` env vars > `domain.toml [logging]`
section > environment-based defaults (`_ENV_LEVEL_MAP`). Before this epic,
`configure_logging()` already applied this precedence chain to the `level`
parameter. Extending the same chain to every logging setting was the natural
step.

### 7. OpenTelemetry trace context: opt-in via `telemetry.enabled`

The tracing epic (Epic 6.1) added OTel spans across the framework. The
correlation epic (Epic 6.5) added correlation IDs to log records. This logging
epic (Epic 6.6) connects the two. When `telemetry.enabled=True`,
`Domain.configure_logging()` installs an `OTelTraceContextFilter` on the root
logger and appends a `protean_otel_processor` to the structlog pipeline. Both
read the active span via `opentelemetry.trace.get_current_span()` and inject
`trace_id`, `span_id`, and `trace_flags` into every log record. Outside a valid
span, or when the `opentelemetry` extra is not installed, the fields default to
empty strings / `0`.

The processor is opt-in *per the existing telemetry gate*, not behind a new
config flag. If the user has opted into OTel, they get log↔trace correlation
too, no extra decision required. If the user has not opted in, Protean never
appends the processor. The structlog chain then has no no-op processor to run
on every log call.

OTel imports happen lazily, on the first call to `_get_otel_trace_context`.
Module-level sentinels cache the result, so after the first call the hot path
is a pure attribute lookup. Merely importing `protean.integrations.logging`
does not trigger an `opentelemetry` import.

### 8. Redaction: processor/filter level, unioned defaults, depth-bounded

Redaction at call sites was considered and rejected within the first few
minutes of design. In real codebases, call-site redaction is the one pattern
that always fails. When a developer writes a new log call and forgets to
redact, that call leaks data. Reviewers cannot reliably catch every such call.

Redaction runs at the **pipeline level**. A stdlib `Filter`
(`ProteanRedactionFilter`) and a structlog processor
(`make_redaction_processor` / `protean_redaction_processor`) mask values whose
keys match the configured list, regardless of where the value originated.
Defaults (`password`, `token`, `secret`, `api_key`, `authorization`, `cookie`,
`session`, `csrf`) are **unioned** with the operator-supplied list, not
substituted. Operators cannot accidentally stop masking a core field by
supplying their own list. A security invariant we explicitly want enforced by
the framework.

Matching is case-insensitive. Recursion into `dict` / `list` / `tuple` is
bounded to `_MAX_REDACT_DEPTH=5` levels. Pathological nested payloads cannot
stall logging. Redaction is a best-effort hygiene filter and offers no security
boundary. Structured sensitive data that an application stores or processes
still belongs in secrets management and should stay out of log fields.

The redaction processor is **appended** to the structlog chain so it runs last,
after all caller-supplied processors (correlation, OTel, tail sampling, custom
enrichment). The redaction processor masks any redacted field in any log event
before the renderer sees it, no matter which step added the field. The ordering
is not optional: if redaction ran earlier, a subsequent processor could add a
sensitive field and bypass the mask.

`log_method_call` now inherits the masking transparently because its DEBUG
records flow through the same pipeline, no per-decorator flag needed.

### 9. Multi-worker log queue: single-process unchanged

Multi-process log interleaving is a real operational problem. Separate `protean
server` worker processes that write JSON records to the same stdout can corrupt
each other at byte boundaries. This happens for records longer than OS
`PIPE_BUF`, which is 4 KB on Linux and 512 bytes on some BSDs. A single
unparseable JSON line breaks the log aggregator's ingestion for the whole line.

`protean server --workers N` (with `N > 1`) now installs a `QueueHandler` on each worker process and a `QueueListener` on the supervisor. Workers push `LogRecord` objects onto a `multiprocessing.Queue`; the supervisor drains the queue and hands records to its own handlers for final rendering. The listener is stopped in a `finally` block on shutdown so records pending in the queue are drained before process exit.

**Single-worker mode is unchanged**, no queue overhead, no extra process, no
behavioural change. Protean installs the queue only when more than one worker
runs, so you pay the queue's cost only when you use it.

### 10. `protean.security` logger: SIEM feed, not a bucket for every error

Operators need a dedicated channel, distinct from the general access log, for
invariant violations, validation failures that cross a domain boundary, and
invalid operation / state exceptions. With that channel, they can route these
events to a SIEM or alerting pipeline, and sampling, tail-keeping rules or
format changes cannot interfere.

`protean.security` emits WARNING events: `invariant_failed`,
`validation_failed`, `invalid_operation`, `invalid_state`. These constants are
exposed as module-level `SECURITY_EVENT_*` values in
`src/protean/integrations/logging/__init__.py`. Call sites use the constants,
so a typo cannot make an event name differ from what operators query in their
aggregators.

The `protean.security` channel is deliberately **narrow**: internal validation
errors that a handler catches and retries never reach it. The
`protean.security` logger emits only events that crossed a domain boundary and
were not recovered (the ones an operator actually wants to see). If every
validation error went to this channel, by week two operators could not find the
real security events among the rest.

### 11. CLI control surface: deprecation pathway for `--debug`

Every CLI subcommand (`server`, `test`, `shell`, `projection`, `snapshot`, `observatory`, `check`, `dlq`, `events`) now accepts global `--log-level`, `--log-format`, and `--log-config` flags inherited from the Typer callback. Precedence: `--log-config` (dictConfig) > `--log-level` / `--log-format` > `Domain.init()` auto-configuration.

`--debug` on `server` and `observatory` is now a **Tier 1 surface-level break**
per ADR-0004. The flag still works. The `--debug` flag delegates to
`configure_logging(level="DEBUG")`. It also emits a `DeprecationWarning`
pointing operators to `--log-level DEBUG`, and the flag will be removed in
v0.17.0. The breaking change policy (ADR-0004) requires a deprecated flag to
keep working for at least two minor versions, and this schedule meets that
minimum. The rest of the epic introduces new APIs and config keys but does not
rename or remove existing ones. All other changes are strictly additive.

Every CLI command wraps its main body in `cli_exception_handler` so unhandled
exceptions are logged with a structured event *before* propagating and killing
the process. Before this change, a traceback to stderr was the only record of
the failure. Now an operator running under a log aggregator sees the failure in
the same structured stream as everything else.

### 12. Slow SQL query detection: adapter-level, not framework-level

Slow-query detection is closely related to slow-handler detection. We
deliberately built slow-query detection into the adapter, and the framework
core does not detect slow queries. The SQLAlchemy repository adapter emits
`protean.adapters.repository.sqlalchemy.slow_query` WARNING events when a query
exceeds `[logging].slow_query_threshold_ms` (default 100 ms), with the query
text truncated to `slow_query_truncate_chars` characters.

We put slow-query detection in the adapter because its behaviour depends on the
driver. SQLAlchemy exposes a native `before_cursor_execute` /
`after_cursor_execute` hook that makes the measurement trivial. Elasticsearch,
memory, and any future adapters would each need their own instrumentation. The
framework defines the configuration settings (`slow_query_threshold_ms`,
`slow_query_truncate_chars`) and the logger-name convention
(`protean.adapters.repository.<adapter>.slow_query`). Each adapter wires its
own detection. The framework uses the same Ports & Adapters split elsewhere:
the port defines the contract, and the adapter owns the driver-specific code.

## Consequences

**Positive:**

- Operators running `protean server` in production now see informative
  JSON-structured wide events. They can answer debugging questions from these
  events without grepping across lines. Each unit of work produces one event,
  which carries sixteen framework-populated fields plus any
  application-specific fields from `bind_event_context()`.
- Log↔trace correlation is automatic when `telemetry.enabled=True`. An operator
  debugging a slow request in Grafana/Tempo can go directly from a span to the
  log event and back.
- All framework log records carry `correlation_id`, `causation_id`, and (when OTel is active) `trace_id` /
  `span_id` / `trace_flags`, without any application code change.
- Sensitive data cannot leak through logs once redaction is configured.
  Operators cannot weaken the defaults by supplying their own list. The
  framework unions that list with the defaults, so the default fields always
  stay masked.
- Multi-worker deployments no longer interleave JSON records at byte boundaries.
- `Domain.init()` auto-configures logging. A developer who never thinks about
  logging still gets sensible defaults.
- Tail sampling lets operators control wide-event cost at scale without losing
  errors and slow requests. With the default rules, the sampler always keeps
  the most valuable events (errors and slow requests).
- FastAPI applications get HTTP wide events with no extra code. Each HTTP wide
  event is correlated with domain-layer wide events by `correlation_id`, and
  every response echoes `X-Request-ID` back.

**Negative:**

- The framework now has two layers of wide events (`protean.access`, `protean.access.http`) that must be kept in sync. Adding a field to one means deciding whether it belongs in the other; drift is a real risk.
- The API contract of `bind_event_context` depends on how structlog contextvars
  behave. Callers in Starlette's child task model need to understand that
  contextvar bindings from an endpoint do not automatically reach the
  middleware. The dual-write to `g._http_wide_event_extras` is a workaround,
  not a solution. Future frameworks with similar child-task semantics will need
  equivalent shims.
- Redaction is a best-effort filter, not a security boundary. Deeply nested
  sensitive data beyond five levels of nesting is not masked. When operators
  need stronger guarantees, they must still avoid logging sensitive structured
  payloads in the first place.
- `bind_event_context()` is silent when called outside a handler. It binds to
  the current contextvars but those bindings will be cleared when the next
  handler starts. Developers can be surprised that a call outside a handler had
  no effect on any visible event.
- Tail sampling must be configured carefully. Suppose an operator sets an
  aggressive `default_rate` (e.g. 0.001) and has not set
  `always_keep_slow=True`. The sampler will then quietly drop the events that
  matter most. The defaults (always keep errors and slow) are the only sensible
  defaults. We did not expose them as defaults-off.
- The `ProcessorFormatter` bridge means stdlib log calls now run through the
  structlog processor chain. On a very hot debug path, this is more work per
  call than the old plain formatter did. In practice, production deployments
  run at INFO and do not emit the DEBUG paths. The cost is therefore paid only
  when debug is explicitly enabled.

## Alternatives Considered

**Mass migration to structlog `get_logger()` in framework internals.**
Rejected. The pipeline bridge gives the same output uniformity with a
~99-module-smaller diff. A hard structlog dependency at every framework
callsite would also limit future library choices.

**Swap structlog for loguru.** Rejected. `loguru` is a single-line-setup
library that optimises for developer convenience in small scripts. Structlog
optimises for composable processor chains in production systems. Structlog's
model maps cleanly onto each of Protean's needs: pipeline integration with
stdlib, processor-level redaction, contextvar-based enrichment, OTel
integration, and tail sampling. Loguru's model does not.

**Custom `ContextVar[WideEvent]` primitive for `bind_event_context`.** Rejected
because structlog's contextvars already solve the problem. Every new
concurrency primitive is a potential source of async-safety bugs. Reusing the
primitive already vetted in production is strictly safer.

**Sample at the head instead of the tail.** Rejected. Head sampling decides at
the start of a request whether to log it. As a result, it loses exactly the
events (errors, slow requests) that operators most want to keep. Tail sampling
costs a little more, since it assembles the event dict regardless. In return,
it never loses the errors and slow requests.

**Instrument each handler with a decorator for wide events.** Rejected. With a
decorator, every handler author would have to remember to apply it. The
framework could then no longer add observability without help from handler
code. The access log emits from the handler-execution layer so no handler
author opts in or out.

**Use middleware for the access log (instead of a dedicated logger).** Rejected
because the framework has no single middleware chain covering command handlers,
event handlers, query handlers, and projectors. Protean emits the dedicated
logger from the handler mixin, so one place in the code serves all four
dispatch paths.

**Email-on-error handler** (Django's `AdminEmailHandler`). Rejected on scope.
Operators should page from the alerting layer, and the logging layer should not
send pages. Operators route `level=ERROR` events from their log aggregator to
PagerDuty or Slack. The framework should not build a second mechanism for that.

**Build a log viewer into Observatory**. Rejected on scope. Observatory is
built to show traces and events. Operators read logs in log aggregators (Loki,
Elasticsearch, CloudWatch). Competing with log aggregator products is out of
scope.

**Single unified `protean.access` logger for HTTP and domain events.**
Considered and rejected because operators need independent routing and sampling
rules for the two layers. A user-agent 4xx rate limit hit and a domain-level
handler failure are different problems with different operational responses. If
one logger name carried both, operators would have to re-split them with regex
at ingestion time.

**Add redaction flags at each call site.** Rejected. Any pattern that relies on
developers remembering to redact in every new log call will eventually fail.
The failure is then a data leak. Pipeline-level redaction, with the default
field list always added to the operator's list, is the only approach that stays
correct under real-world refactoring.

## References

- Epic 6.6: Logging Overhaul (#912), design decisions and sub-issue breakdown
- Structured logging baseline and stdlib→structlog pipeline bridge (sub-issue
  #913)
- Auto-configuration on `Domain.init()` and `[logging]` config section
  (sub-issue #914)
- CLI logging control surface (sub-issue #915)
- Wide event access log, domain context enrichment, slow-handler detection
  (sub-issue #916)
- OpenTelemetry trace context injection (sub-issue #917)
- Slow SQL query detection in SQLAlchemy repository adapter (sub-issue #918)
- Sensitive-field redaction, multi-worker log queue, `protean.security` logger
  (sub-issue #919)
- Tail sampling for wide events (sub-issue #924)
- FastAPI HTTP-layer wide event middleware (sub-issue #925)
- Logging documentation overhaul (guide, reference, concept pages) (sub-issue
  #920)
- Release Workflow and Breaking Change Policy (ADR-0004): classification for
  the `--debug` deprecation
- Domain-Scoped OpenTelemetry Providers (ADR-0007): log↔trace correlation
  precursor
- Centralized Telemetry Gateway and TraceParent Bridging (ADR-0008): log↔trace
  correlation companion
- [Jamie Brandon, *Logging Sucks, So Use Wide Events*](https://loggingsucks.com): Wide event pattern
