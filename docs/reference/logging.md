# Logging

Factual reference for Protean's structured logging system. For task-oriented
instructions see the [Logging guide](../guides/server/logging.md); for design
rationale see the [Logging concepts](../concepts/observability/logging.md)
page.

---

## `[logging]` config section

`domain.toml`:

```toml
[logging]
level = "INFO"
format = "auto"
log_dir = ""
log_file_prefix = "protean"
max_bytes = 10485760
backup_count = 5
slow_handler_threshold_ms = 500
slow_query_threshold_ms = 100
slow_query_truncate_chars = 500
redact = ["password", "token", "secret", "api_key", "authorization", "cookie", "session", "csrf"]

[logging.per_logger]
"protean.server.engine" = "WARNING"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `level` | str | `""` (environment default) | Root log level. `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. Empty = use the environment-based default. |
| `format` | str | `"auto"` | Output format. `"json"` forces JSON; `"console"` forces colored console; `"auto"` picks based on `PROTEAN_ENV`. |
| `log_dir` | str | `""` | Directory for rotating file handlers. Empty disables file logging (stdout only). |
| `log_file_prefix` | str | `"protean"` | Prefix for log file names. Produces `<prefix>.log` and `<prefix>_error.log`. |
| `max_bytes` | int | `10485760` (10 MB) | Max size per rotating log file before rotation. |
| `backup_count` | int | `5` | Number of rotated files to retain. |
| `slow_handler_threshold_ms` | float | `500` | Duration in ms above which a handler emits a `protean.perf.slow_handler` WARNING and the wide event is tagged `status="slow"`. Set to `0` to disable slow-handler tagging. |
| `slow_query_threshold_ms` | float | `100` | Duration in ms above which a SQLAlchemy query emits a `protean.adapters.repository.sqlalchemy.slow_query` WARNING. |
| `slow_query_truncate_chars` | int | `500` | Max SQL statement length in the slow-query log event. Trailing characters are replaced with `...`. `0` disables truncation. |
| `redact` | list[str] | see [Redaction](#redaction) | Additional keys (case-insensitive) to mask with `[REDACTED]`. Unioned with the built-in defaults — never replaces them. |
| `per_logger` | table | `{}` | Map of logger name → level. Applied after the global setup so individual loggers can be tuned. |

### Precedence

Effective values are resolved in this order (first match wins):

1. Explicit keyword arguments to `Domain.configure_logging()` (or
   `configure_logging()` directly)
2. `PROTEAN_LOG_LEVEL` environment variable (for `level` only)
3. `domain.toml [logging]` section
4. Environment-based defaults (see below)

### Environment defaults

When `level` is empty and `PROTEAN_LOG_LEVEL` is unset, Protean picks a
default from `PROTEAN_ENV` (falling back to `ENV` / `ENVIRONMENT`):

| `PROTEAN_ENV` | `level` default | `format` default |
|---------------|-----------------|------------------|
| `development` | `DEBUG` | colored console |
| `production` | `INFO` | JSON |
| `staging` | `INFO` | JSON |
| `test` | `WARNING` | colored console |
| (unset) | `DEBUG` | colored console (treated as development) |

---

## CLI flags

Every `protean` command accepts three global logging flags, evaluated in the
root callback before any subcommand runs:

| Flag | Values | Behavior |
|------|--------|----------|
| `--log-level` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` | Overrides the resolved level. Invalid values exit with code `2`. |
| `--log-format` | `auto` \| `console` \| `json` | Overrides the resolved format. Invalid values exit with code `2`. |
| `--log-config` | path to JSON file | Applies the JSON as a `logging.config.dictConfig`. Mutually exclusive with `--log-level` / `--log-format`: when present, they are ignored. |

`protean server --debug` is deprecated and will be removed in v0.17.0. It is
equivalent to `--log-level DEBUG`.

When any of these flags are used, CLI commands skip the later `Domain.init()`
auto-configuration to avoid clobbering the explicit setup.

---

## Environment variables

| Variable | Purpose | Accepted values |
|----------|---------|-----------------|
| `PROTEAN_ENV` | Deployment environment; drives default level and format. | `development`, `staging`, `production`, `test` (case-insensitive). Falls back to `ENV`, then `ENVIRONMENT`. Default: `development`. |
| `PROTEAN_LOG_LEVEL` | Overrides the resolved level (but not an explicit `level` kwarg). | Same as `--log-level`. |
| `PROTEAN_NO_AUTO_LOGGING` | Disables `Domain.init()` auto-configuration. | `1` or `true` (case-insensitive). Anything else is ignored. |

---

## Public API

### `configure_logging`

```python
from protean.utils.logging import configure_logging

configure_logging(
    level=None,
    format="auto",
    log_dir=None,
    log_file_prefix=None,
    max_bytes=10 * 1024 * 1024,
    backup_count=5,
    extra_processors=None,
    per_logger=None,
    dict_config=None,
    redact=None,
)
```

Installs handlers, configures structlog, and wires the `ProcessorFormatter`
bridge so stdlib `logging.getLogger()` records flow through the same
processor chain as `get_logger()` events.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `level` | `str \| None` | `None` | Resolved via env vars when `None`. |
| `format` | `"auto" \| "json" \| "console"` | `"auto"` | Output format. |
| `log_dir` | `str \| Path \| None` | `None` | Enables rotating file handlers when set. |
| `log_file_prefix` | `str \| None` | `"protean"` | Prefix for log file names. |
| `max_bytes` | `int` | `10 MB` | Rotation size. |
| `backup_count` | `int` | `5` | Number of rotated files. |
| `extra_processors` | `list \| None` | `None` | Additional structlog processors inserted before the renderer. Redaction is appended after these so operator-supplied processors cannot smuggle sensitive values past it. |
| `per_logger` | `dict[str, str] \| None` | `None` | Applied after main setup. |
| `dict_config` | `dict \| None` | `None` | When provided, bypasses the environment-aware setup and applies `logging.config.dictConfig()`. The `ProteanCorrelationFilter` is still installed on the root logger. |
| `redact` | `list[str] \| None` | `None` | Adds keys (case-insensitive) to the redact list; always unioned with [`DEFAULT_REDACT_KEYS`](#redaction). |

### `Domain.configure_logging`

```python
domain.configure_logging(**kwargs)
```

Merges `domain.toml [logging]` with explicit kwargs, calls
`configure_logging()`, and installs:

- `ProteanCorrelationFilter` on the root stdlib logger
- `protean_correlation_processor` on the structlog pipeline
- `OTelTraceContextFilter` + `protean_otel_processor` when
  `telemetry.enabled = true`

Idempotent — calling it again replaces handlers and de-duplicates filters.

### `get_logger`

```python
from protean.utils.logging import get_logger

logger = get_logger(__name__)
logger.info("order_placed", order_id="ord-123", total=99.95)
```

Returns a `structlog.stdlib.BoundLogger` wrapping the stdlib logger of the
given name.

### `bind_event_context` / `unbind_event_context`

```python
from protean.utils.logging import bind_event_context, unbind_event_context

bind_event_context(user_id="u-42", plan="premium")
unbind_event_context("plan")
```

Adds or removes business-specific fields on the **current wide event**.
Uses `structlog.contextvars`, which is async-safe and thread-local — each
coroutine or thread sees its own bindings.

The `access_log_handler` context manager snapshots outer bindings at
handler entry, clears them for a clean handler scope, and restores them
on exit. Fields that collide with framework-reserved names or stdlib
`LogRecord` attributes are stripped before emission to protect the
logging contract.

Framework-reserved names that cannot be overwritten by application context:

```
kind, message_type, message_id, aggregate, aggregate_id,
events_raised, events_raised_count, repo_operations, uow_outcome,
handler, duration_ms, status, error_type, error_message,
correlation_id, causation_id
```

### `add_context` / `clear_context`

```python
from protean.utils.logging import add_context, clear_context

add_context(request_id="req-abc", tenant_id="tenant-42")
clear_context()
```

Binds request-scoped context to every subsequent log record (not just wide
events). Uses the same `structlog.contextvars` store as
`bind_event_context`.

### `log_method_call`

```python
from protean.utils.logging import log_method_call

class PlaceOrderHandler:
    @log_method_call
    def handle(self, command):
        ...
```

Logs `method_call_start` / `method_call_end` / `method_call_error` at
DEBUG. Arguments and keyword arguments are included on the event dict and
pass through the configured redaction filter.

### `configure_for_testing`

```python
from protean.utils.logging import configure_for_testing

configure_for_testing()
```

Sets the root logger to WARNING and removes any `FileHandler` attached to
the root logger. Use in `conftest.py` to minimize test noise.

---

## Framework logger catalog

Every logger below is a stdlib `logging.Logger`. Events flow through the
same `ProcessorFormatter` pipeline as `get_logger()` calls, so JSON output
and console output share a single rendering pass.

Field types in each subsection describe the values emitted via the `extra`
dict. Every record also carries `correlation_id`, `causation_id`, and —
when `telemetry.enabled = true` — `trace_id`, `span_id`, `trace_flags`.

### `protean.access`

Level: INFO on success, WARNING on `status="slow"`, ERROR on `status="failed"`.

One wide event per handled command, event, query, or projector invocation.

#### `access.handler_completed`

Emitted once per successful or slow handler execution.

| Field | Type | Notes |
|-------|------|-------|
| `kind` | `"command" \| "event" \| "query" \| "projector"` | Handler kind. |
| `message_type` | `str` | e.g. `"PlaceOrder"`. Uses `__type__` when set, else `__class__.__name__`. |
| `message_id` | `str` | Message envelope id; `""` outside the server engine path. |
| `aggregate` | `str` | Aggregate class name; `""` for handlers without a `part_of`. |
| `aggregate_id` | `str` | Extracted from the message stream when deducible; `""` otherwise. |
| `events_raised` | `list[str]` | Event class names raised during the handler. |
| `events_raised_count` | `int` | `len(events_raised)`. |
| `repo_operations` | `{"loads": int, "saves": int}` | Repository load / save counts. |
| `uow_outcome` | `"committed" \| "rolled_back" \| "no_uow"` | |
| `handler` | `str` | `"ClassName.method"`. |
| `duration_ms` | `float` | Handler duration, rounded to 2 decimals. |
| `status` | `"ok" \| "slow" \| "failed"` | `slow` when `duration_ms > slow_handler_threshold_ms`. |
| `error_type` | `str \| None` | Always `None` on success. |
| `error_message` | `str \| None` | Always `None` on success. |
| **Application fields** | any | Everything passed to `bind_event_context()` in the handler. |

#### `access.handler_failed`

Emitted once per failing handler execution, at ERROR with `exc_info` set
so the traceback is preserved in the rendered output.

Same fields as `access.handler_completed`, plus:

| Field | Type | Notes |
|-------|------|-------|
| `error_type` | `str` | Exception class name. |
| `error_message` | `str` | `str(exc)` truncated to 256 characters. |

---

### `protean.perf`

Level: WARNING. Holds slow-handler alerts so operators can route them
independently from the success log.

#### `slow_handler`

Emitted immediately after `access.handler_completed` with `status="slow"`.
Same field set as the wide event.

---

### `protean.security`

Level: WARNING. A dedicated channel for invariant, validation, and
authorization failures that cross a domain boundary. Populate via
`protean.integrations.logging.log_security_event(event_type, **fields)`.

| Event name | Emitted for |
|------------|-------------|
| `invariant_failed` | Aggregate invariant violation reaching a domain boundary. |
| `validation_failed` | `ValidationError` raised while dispatching a command through the API or a command handler. |
| `invalid_operation` | `InvalidOperationError` raised from a domain method. |
| `invalid_state` | `InvalidStateError` raised from a domain method. |

Common fields on every emission:

| Field | Type | Notes |
|-------|------|-------|
| `correlation_id` | `str` | Auto-injected from active context. |
| `causation_id` | `str` | Auto-injected from active context. |
| `aggregate` | `str` | Set by the caller when relevant. |
| `aggregate_id` | `str` | Set by the caller when relevant. |
| `invariant` | `str` | On `invariant_failed`. |

Additional caller-supplied fields pass through, except keys colliding with
stdlib `LogRecord` attributes which are silently dropped.

---

### `protean.server.engine`

Engine lifecycle events. DEBUG-level events are only visible when the root
logger is set to DEBUG; everything else is audible at INFO.

| Event | Level | Fields |
|-------|-------|--------|
| `engine.starting` | DEBUG | |
| `engine.subscription_started` | INFO | `subscription` |
| `engine.broker_subscription_started` | INFO | `subscription` |
| `engine.outbox_processor_started` | INFO | `processor` |
| `engine.dlq_maintenance_started` | INFO | |
| `engine.draining_tasks` | DEBUG | `count` |
| `engine.shutting_down` | INFO | |
| `engine.subscriptions_stopped` | INFO | |
| `engine.stopped` | INFO | |
| `engine.no_subscriptions` | WARNING | |
| `engine.outbox_disabled` | DEBUG | |
| `engine.outbox_initializing` | DEBUG | |
| `engine.creating_outbox_processor` | DEBUG | `processor` |
| `engine.dlq_maintenance_init_skipped` | DEBUG (exc) | |
| `engine.error_handler_failed` | ERROR (exc) | |
| `engine.cleanup_failed` | ERROR (exc) | |

---

### `protean.server.subscription`

Lifecycle and error events for the per-subscriber processing loop.

| Event | Level | Fields |
|-------|-------|--------|
| `subscription.started` | INFO | `subscriber` |
| `subscription.cancelled` | INFO | `subscriber` |
| `subscription.shutdown` | INFO | `subscriber` |
| `subscription.error` | ERROR (exc) | `subscriber`, `attempt` |

Per-message handler timing and completion flow through the dedicated
`protean.access` logger (see above), not through this logger.

---

### `protean.server.outbox_processor`

Outbox lifecycle and batch publishing. Per-message publish outcomes are
emitted as trace events via the engine emitter, not as log records — they
do not appear on this logger.

| Event | Level | Fields |
|-------|-------|--------|
| `outbox.initializing` | DEBUG | `database_provider`, `broker_provider` |
| `outbox.broker_selected` | DEBUG | `broker` |
| `outbox.repo_selected` | DEBUG | `repo` |
| `outbox.initialized` | DEBUG | `database_provider`, `broker_provider` |
| `outbox.batch_fetched` | DEBUG | `count` |
| `outbox.batch_completed` | INFO | `total`, `successful`, `failed` |
| `outbox.message_already_claimed` | DEBUG | `message_id` |
| `outbox.message_published` | DEBUG | `message_id`, `broker` |
| `outbox.publish_failed` | WARNING | `message_id`, `error_type`, `error` |
| `outbox.processing_error` | ERROR (exc) | `message_id` |
| `outbox.status_save_failed` | ERROR (exc) | `message_id` |
| `outbox.broker_published` | DEBUG | `message_id`, `broker_message_id` |
| `outbox.broker_publish_failed` | ERROR (exc) | `message_id` |
| `outbox.cleanup` | DEBUG | `database_provider`, `broker_provider` |
| `outbox.cleanup_completed` | INFO | `total`, `published`, `abandoned` |
| `outbox.cleanup_failed` | ERROR (exc) | |

---

### `protean.core.unit_of_work`

Transaction-boundary events. DEBUG covers the happy path; commit/rollback
failures use `logger.exception(...)` so stack traces are preserved.

| Event | Level | Fields |
|-------|-------|--------|
| `uow.committing` | DEBUG | `uow_id` |
| `uow.commit_successful` | DEBUG | |
| `uow.commit_failed` | ERROR (exc) | |
| `uow.rollback_successful` | DEBUG | |
| `uow.rollback_failed` | ERROR (exc) | |

---

### `protean.adapters.broker.redis`

Failures on the Redis broker adapter. Most events are emitted via
`logger.exception(...)` so the traceback is preserved; the structured
event name doubles as the query key.

| Event | Level |
|-------|-------|
| `broker.redis.connection_exhausted` | ERROR |
| `broker.redis.reconnect_failed` | ERROR (exc) |
| `broker.redis.read_failed` | ERROR (exc) |
| `broker.redis.read_blocking_failed` | ERROR (exc) |
| `broker.redis.get_next_failed` | ERROR (exc) |
| `broker.redis.ack_failed` | ERROR (exc) |
| `broker.redis.nack_failed` | ERROR (exc) |
| `broker.redis.nogroup_retry_failed` | ERROR (exc) |
| `broker.redis.deserialize_failed` | ERROR (exc) |
| `broker.redis.health_check_failed` | ERROR (exc) |
| `broker.redis.info_failed` | ERROR (exc) |
| `broker.redis.data_reset_failed` | ERROR (exc) |

`broker.redis.connection_exhausted` carries `max_attempts`; the other
events rely on the traceback rather than per-record `extra` fields.

### `protean.adapters.broker.inline`

| Event | Level |
|-------|-------|
| `broker.inline.ack_failed` | ERROR (exc) |
| `broker.inline.nack_failed` | ERROR (exc) |
| `broker.inline.nack_handle_failed` | ERROR (exc) |
| `broker.inline.dlq_reprocess_failed` | ERROR (exc) |

### `protean.adapters.broker.redis_pubsub`

| Event | Level |
|-------|-------|
| `broker.redis_pubsub.health_check_failed` | WARNING |
| `broker.redis_pubsub.data_reset_failed` | ERROR (exc) |

---

### `protean.adapters.repository.sqlalchemy`

Level: WARNING. The adapter installs SQLAlchemy engine listeners at
provider construction time.

#### `repository.sqlalchemy.slow_query`

Emitted on the `protean.adapters.repository.sqlalchemy.slow_query` child
logger whenever a query's duration exceeds `slow_query_threshold_ms`.

| Field | Type | Notes |
|-------|------|-------|
| `statement` | `str` | SQL statement, truncated to `slow_query_truncate_chars` with trailing `...` when cut. |
| `parameters` | `Any` | Bound parameters. Pass through the redaction filter. |
| `duration_ms` | `float` | Measured from `before_cursor_execute` to `after_cursor_execute`. |
| `threshold_ms` | `float` | Effective threshold at emission. |

#### `repository.sqlalchemy.query`

Emitted on the sibling `protean.adapters.repository.sqlalchemy.query`
logger at DEBUG for every query. Off by default — enable by setting its
level to `DEBUG` in `[logging.per_logger]`.

Same field set as `slow_query`, minus `threshold_ms`.

---

### `protean.adapters.repository.elasticsearch`

Level: WARNING. Index lifecycle and query failures. Event names follow
`repository.elasticsearch.<event>`.

---

## Trace-context fields

When `telemetry.enabled = true` in `domain.toml`,
`Domain.configure_logging()` installs `OTelTraceContextFilter` on the root
stdlib logger and `protean_otel_processor` on the structlog pipeline.
Every log record receives:

| Field | Type | Notes |
|-------|------|-------|
| `trace_id` | `str` | 32-char hex; `""` when no active span. |
| `span_id` | `str` | 16-char hex; `""` when no active span. |
| `trace_flags` | `int` | `0` or `1`; `0` when no active span. |

The helpers are lazy — when `opentelemetry` is not installed they return
`("", "", 0)` and cache that decision, so telemetry-disabled deployments
pay no per-record cost.

---

## Correlation fields

Always present on every record when auto-configuration is active:

| Field | Type | Notes |
|-------|------|-------|
| `correlation_id` | `str` | From `g.message_in_context.metadata.domain.correlation_id`, falling back to `g.correlation_id`. `""` outside any domain context. |
| `causation_id` | `str` | Same extraction path, falling back to `g.causation_id`. |

See [Correlation and Causation IDs](../guides/observability/correlation-and-causation.md)
for how IDs propagate across HTTP headers, OTel spans, events, and CLI
commands.

---

## Redaction

Values whose keys match the configured list are replaced with the literal
string `[REDACTED]`. Matching is case-insensitive. Nested `dict`, `list`,
and `tuple` values are scanned up to **5 levels deep**; deeper nesting is
left untouched.

### Default redact keys

```
password, token, secret, api_key, authorization, cookie, session, csrf
```

These defaults are always applied. The `[logging].redact` list is
**unioned** with them — operators cannot disable a core protection by
supplying their own list.

### Extending the list

```toml
[logging]
redact = ["x-internal-token", "customer_ssn"]
```

### Where redaction runs

- **structlog pipeline:** the processor returned by
  `make_redaction_processor()` is appended to `extra_processors` so it
  runs **last**, after every caller-supplied processor.
- **stdlib pipeline:** `ProteanRedactionFilter` is attached to the root
  logger (when a redact list is configured).
- **`log_method_call`:** inherits redaction transparently because it
  routes through the same pipeline.

See the [concept page](../concepts/observability/logging.md#why-redaction-is-processor-based)
for why redaction runs as a pipeline stage rather than at call sites.

---

## Multi-worker logging

`protean server --workers N` (with `N > 1`) installs a
`logging.handlers.QueueHandler` as the sole root handler for each worker
and a `logging.handlers.QueueListener` on the supervisor that drains the
queue and forwards records to the supervisor's configured handlers.

The listener is stopped in a `finally` block on shutdown so buffered
records are flushed before the supervisor exits. Single-worker mode is
unchanged — no queue overhead.

See [`protean.server.supervisor`](server/supervisor.md) for supervisor
configuration, and the
[concept page](../concepts/observability/logging.md#multi-worker-hygiene)
for the rationale.
