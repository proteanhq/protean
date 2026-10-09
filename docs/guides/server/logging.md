# Logging

Protean ships with structured logging that configures itself. Call
`domain.init()` and every log line (from framework internals, your handler
code, and the SQLAlchemy adapter) flows through the same `structlog` pipeline
as JSON in production and colored console output in development.

The tasks operators and application developers do most often are below. For
the full schema of every framework event and every config key, see
the [Logging reference](../../reference/logging.md). For the design rationale
behind the wide event pattern, see
[Logging concepts](../../concepts/observability/logging.md).

---

## Quick start

```python
--8<-- "guides/server/logging/quick-start/001.py:quick-start"
```

That is the whole setup. `Domain.init()` auto-detects `PROTEAN_ENV`, picks a
sensible level and format, and installs correlation injection so every log
record is queryable by `correlation_id`. When `telemetry.enabled = true`,
Protean additionally injects OpenTelemetry `trace_id`, `span_id`, and
`trace_flags` so logs line up with traces in your APM tool.

The default level and format depend on the environment. Protean reads
`PROTEAN_ENV`, then `ENV`, then `ENVIRONMENT`:

| Environment | Level | Format |
|-------------|-------|--------|
| `development` | `DEBUG` | colored console |
| `production`, `staging` | `INFO` | JSON |
| `test` | `WARNING` | colored console |
| unset, or any other value | `INFO` | colored console |

With no environment variable set, a script or a REPL session logs at `INFO`,
so `domain.init()` writes no `DEBUG` lines. At `INFO`, Protean holds
`protean.core` and `protean.adapters` at `WARNING`, so their `INFO` lines, such
as `Executing use case`, do not show either. To see the framework's `DEBUG`
lines, do one of these:

- set `PROTEAN_ENV=development`
- set `PROTEAN_LOG_LEVEL=DEBUG`
- pass the global flag before the command: `protean --log-level DEBUG <command>`
- set `level = "DEBUG"` under `[logging]` in `domain.toml`

To log from application code:

```python
--8<-- "guides/server/logging/001.py:get-logger"
```

Keyword arguments become structured fields in JSON output and colored
key-value pairs in console output. Prefer keyword arguments over
f-strings so values remain queryable downstream, see [why structured
logs?](../../concepts/observability/logging.md#why-structured-logs) for the
rationale.

!!! warning "Known issue: keyword arguments nest inside `event` in JSON output"
    With the JSON format, a `get_logger()` call is rendered to JSON twice. The
    keyword arguments end up inside the outer `"event"` string, not as
    top-level fields. Console output is not affected.

### What a wide event looks like

When a command handler runs, Protean emits one wide event on the
`protean.access` logger. Under `PROTEAN_ENV=production` the renderer is
JSON:

```json
{
  "event": "access.handler_completed",
  "level": "info",
  "logger": "protean.access",
  "timestamp": "2026-04-23T10:15:32.418912Z",
  "kind": "command",
  "message_type": "PlaceOrder",
  "aggregate": "Order",
  "aggregate_id": "ord-9b1c",
  "events_raised": ["OrderPlaced"],
  "events_raised_count": 1,
  "repo_operations": {"loads": 0, "saves": 1},
  "uow_outcome": "committed",
  "handler": "PlaceOrderHandler.handle_place_order",
  "duration_ms": 14.27,
  "status": "ok",
  "correlation_id": "req-abc-123",
  "causation_id": ""
}
```

A failing handler lifts the level to `error`, flips `status` to `"failed"`,
and preserves the traceback:

```json
{
  "event": "access.handler_failed",
  "level": "error",
  "logger": "protean.access",
  "kind": "command",
  "message_type": "ChargeCard",
  "handler": "ChargeCardHandler.handle_charge_card",
  "duration_ms": 842.13,
  "status": "failed",
  "error_type": "PaymentDeclined",
  "error_message": "Insufficient funds",
  "correlation_id": "req-def-456",
  "exception": "Traceback (most recent call last):\n  ..."
}
```

Running under `PROTEAN_ENV=development` swaps the JSON renderer for a
colored `ConsoleRenderer`, with the same fields inline as
`key=value` pairs. See the [Logging reference](../../reference/logging.md#proteanaccess)
for the full field list.

---

## Configure via `domain.toml`

The `[logging]` section is the declarative control surface. A typical
production configuration:

```toml
[logging]
level = "INFO"
format = "json"
log_dir = "/var/log/myapp"
redact = ["x-internal-token"]

[logging.per_logger]
"myapp.orders" = "DEBUG"
```

Every key is optional. See the
[reference page](../../reference/logging.md#logging-config-section) for
the full key list, types, defaults, and precedence rules.

---

## Override from the CLI

Every `protean` command accepts three global flags that take precedence over
`domain.toml`. They are defined on the top-level callback, so they must precede
the subcommand:

```bash
protean --log-level DEBUG server
protean --log-format json server
protean --log-config ./logging.json server      # full dictConfig JSON
```

`--log-level` and `--log-format` override only the level and the format. The
rest of `[logging]` still applies, so redaction, `per_logger` levels, and the
correlation filter stay in place while you raise the verbosity.

`--log-config` applies the supplied JSON via `logging.config.dictConfig()`,
and `server` and `observatory` then skip the domain's `[logging]` section. The
correlation filter is still installed on the root logger and on each handler
your `dictConfig` puts on it. Add the redaction filter to your `dictConfig`
yourself if you need it. If your application adds a handler to the root logger
after logging is configured, add the filters to that handler yourself. The
same goes for handlers your `dictConfig` puts on named loggers, and for child
loggers that set `propagate = False`: their records never reach the root
logger's handlers. A later call to `protean.utils.logging.configure_logging()`
without `dict_config` replaces the root handlers and leaves the new ones
without the correlation filter; call `Domain.configure_logging()` again to
attach it. If your
`dictConfig` leaves the root logger without handlers, `Domain.init()` applies `[logging]`
anyway.

The `--debug` flag on `protean server` and `protean observatory` was removed in
v0.17.0. Use `protean --log-level DEBUG server` instead. The flag works the same
way for multi-worker (`--workers N`) and `--reload` runs: `--log-level`,
`--log-format` and `--log-config` reach every worker process, and each worker
applies them the way the parent does.

---

## Override programmatically

When `domain.toml` is not the right shape (tests, one-off scripts, embedded
domains) call `Domain.configure_logging()` directly. Explicit keyword arguments
override `domain.toml` but still read `PROTEAN_LOG_LEVEL` as an override for
`level` unless `level=` is passed:

```python
--8<-- "guides/server/logging/002.py:configure"
```

If you already called `domain.init()`, calling `configure_logging()` again
replaces the handlers and re-installs the correlation filter. This is safe
to do in tests to reset state.

---

## Enrich wide events with business context

Protean emits one wide event per handled command, event, query, or
projector on the `protean.access` logger. The framework fills in domain
context automatically; application code adds business-specific fields
with `bind_event_context()`:

```python
--8<-- "guides/server/logging/003.py:model"
--8<-- "guides/server/logging/003.py:handler"
```

The framework and application fields merge into the single wide event
emitted when the handler returns. See the [reference](../../reference/logging.md#bind_event_context-unbind_event_context)
for field-reservation rules and the
[concept page](../../concepts/observability/logging.md#query-oriented-field-design)
for guidance on choosing queryable dimensions.

---

## Use structured events in application code

`get_logger()` returns a structlog logger bound to the stdlib logger of the
given name. Events are keyword arguments, not f-strings:

```python
--8<-- "guides/server/logging/001.py:refund"
```

For context that should appear on every record inside a scope, use
`add_context()`:

```python
--8<-- "guides/server/logging/001.py:context"
```

`add_context()` uses `contextvars`, so it propagates correctly across
`await` boundaries and thread-local scope.

---

## Control wide event volume with tail sampling

By default Protean emits one wide event per handled message. At scale (millions
of messages per day) this can become expensive to store and query. **Tail
sampling** keeps every error and slow request (the events that actually help
you debug) and samples the happy path at a configurable rate.

Enable it declaratively:

```toml
[logging.sampling]
enabled = true
default_rate = 0.05         # keep 5 % of happy-path events
always_keep_errors = true   # status="failed" / ERROR+ level
always_keep_slow = true     # status="slow"
critical_streams = ["Payment*", "Auth*"]   # fnmatch globs on message_type
```

Every kept event carries three metadata fields so log aggregators can
compute accurate throughput from sampled data:

```json
{
  "event": "access.handler_completed",
  "sampling_decision": "kept",
  "sampling_rule": "random",
  "sampling_rate": 0.05
}
```

To reconstruct the true count: `actual_count = sampled_count / sampling_rate`.

Rules apply in order; first match wins: `always_keep_errors` →
`always_keep_slow` → `critical_streams` → random sampling at `default_rate`.
See the [reference](../../reference/logging.md#loggingsampling)
for per-key details and the
[concept page](../../concepts/observability/logging.md#tail-sampling-keep-what-matters-at-scale)
for why tail sampling beats head sampling.

!!! warning "Keep the safety defaults on"
    Setting `always_keep_errors = false` or `always_keep_slow = false`
    combined with a low `default_rate` will silently drop the events you
    most want to see. The safety defaults exist for a reason.

---

## Emit a security event

`protean.security` is a dedicated channel for invariant, validation, and
authorization failures that cross a domain boundary. Framework code emits
to this channel automatically for aggregate invariant violations and the
three `Invalid*` exceptions. To emit from application code:

```python
--8<-- "guides/server/logging/004.py:security"
```

`correlation_id` and `causation_id` are auto-injected from the active
domain context. Route this logger to your SIEM with no sampling or
format filters attached so every entry is delivered intact. See the
[reference](../../reference/logging.md#proteansecurity) for the full list
of framework-emitted event types.

---

## Disable auto-configuration

When Protean is embedded inside an application that already configured its
own logging (Django, a custom server, an OS-level journald shim), set
`PROTEAN_NO_AUTO_LOGGING=1` before calling `domain.init()`:

```bash
export PROTEAN_NO_AUTO_LOGGING=1
```

Single-worker `protean server` and `protean observatory` honor it too: they
leave any logging your domain module sets up on import in place. The worker
processes of a multi-worker or `--reload` run do not read it. They apply
`[logging]`, or the `--log-config` file when you pass one.

You can then wire whichever parts of Protean's integration you want
manually:

```python
--8<-- "guides/server/logging/005.py:filter"
```

Attach the filter to each handler on the root logger. A filter on a logger
runs only for records logged on that logger, so a filter on the root logger
misses records from child loggers such as `logging.getLogger("myapp.orders")`.

`Domain.init()` also detects a pre-configured root logger (handlers already
attached) and skips its auto-configuration in that case, so in many
embedded setups no env var is needed.

---

## Minimize noise in tests

In `conftest.py`:

```python
--8<-- "guides/server/logging/006.py:testing"
```

This sets the root logger to WARNING and removes file handlers. Tests that
assert on log output with pytest's `caplog` fixture still work because
structlog writes to stdlib handlers.

---

## See also

- **[Logging reference](../../reference/logging.md)**: Every config key, every
  framework logger, every event schema. Includes the `@log_method_call`
  decorator for handler-method entry/exit tracing at DEBUG.
- **[Logging concepts](../../concepts/observability/logging.md)**: Wide events,
  query-oriented field design, backend selection, what Protean deliberately
  does not do.
- **[Correlation and Causation IDs](../observability/correlation-and-causation.md)**:
  how `correlation_id` propagates through commands, events, HTTP headers, OTel
  spans, and log records.
- **[OpenTelemetry Integration](./opentelemetry.md)**: Distributed tracing
  and how `trace_id` / `span_id` reach log records.
- **[FastAPI HTTP wide events](../fastapi/http-wide-events.md)**: One wide
  event per HTTP request, correlated with the domain-layer access log.
- **[Production Deployment](./production-deployment.md)**: Container
  deployment, supervisor configuration, multi-worker mode (see also the
  [multi-worker logging](../../reference/logging.md#multi-worker-logging)
  reference for the `QueueHandler` / `QueueListener` hygiene pattern).
