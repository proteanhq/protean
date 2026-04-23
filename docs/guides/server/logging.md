# Logging

Protean ships with structured logging that configures itself. Call
`domain.init()` and every log line — from framework internals, your handler
code, and the SQLAlchemy adapter — flows through the same `structlog`
pipeline as JSON in production and colored console output in development.

This guide covers the tasks operators and application developers perform most
often. For the full schema of every framework event and every config key, see
the [Logging reference](../../reference/logging.md). For the design rationale
behind the wide event pattern, see
[Logging concepts](../../concepts/observability/logging.md).

---

## Quick start

```python
from protean import Domain

domain = Domain()
domain.init()  # auto-configures logging
```

That is the whole setup. `Domain.init()` auto-detects `PROTEAN_ENV`, picks a
sensible level and format, and installs correlation + OpenTelemetry trace
context injection so every log record is queryable by `correlation_id` and
`trace_id`.

To log from application code:

```python
from protean.utils.logging import get_logger

logger = get_logger(__name__)
logger.info("order_placed", order_id="ord-123", total=99.95)
```

Keyword arguments become structured fields in JSON output and colored
key-value pairs in console output. Prefer keyword arguments over
f-strings so values remain queryable downstream — see
[why structured logs?](../../concepts/observability/logging.md#why-structured-logs)
for the rationale.

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
`domain.toml`:

```bash
protean server --log-level DEBUG
protean server --log-format json
protean server --log-config ./logging.json      # full dictConfig JSON
```

`--log-config` bypasses the environment-aware setup and applies the supplied
JSON via `logging.config.dictConfig()`. The correlation filter is still
installed on the root logger afterwards.

`protean server --debug` is deprecated in favor of `--log-level DEBUG` and
will be removed in v0.17.0.

---

## Override programmatically

When `domain.toml` is not the right shape — tests, one-off scripts, embedded
domains — call `Domain.configure_logging()` directly. Explicit keyword
arguments override `domain.toml` but still read `PROTEAN_LOG_LEVEL` as an
override for `level` unless `level=` is passed:

```python
domain.configure_logging(level="DEBUG", format="json")
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
from protean import handle
from protean.utils.logging import bind_event_context

@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> None:
        bind_event_context(
            user_tier=command.user_tier,
            order_total=float(command.total),
            coupon_applied=command.coupon_code is not None,
        )
        # ... handler logic ...
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
from protean.utils.logging import get_logger

logger = get_logger(__name__)
logger.info("payment_refunded", order_id="ord-123", amount=19.99, reason="customer_request")
```

For context that should appear on every record inside a scope, use
`add_context()`:

```python
from protean.utils.logging import add_context, clear_context

add_context(request_id="abc-123", tenant_id="tenant-42")
try:
    logger.info("processing")          # includes request_id and tenant_id
    logger.info("processed")
finally:
    clear_context()
```

`add_context()` uses `contextvars`, so it propagates correctly across
`await` boundaries and thread-local scope.

---

## Disable auto-configuration

When Protean is embedded inside an application that already configured its
own logging (Django, a custom server, an OS-level journald shim), set
`PROTEAN_NO_AUTO_LOGGING=1` before calling `domain.init()`:

```bash
export PROTEAN_NO_AUTO_LOGGING=1
```

You can then wire whichever parts of Protean's integration you want
manually:

```python
import logging
from protean.integrations.logging import ProteanCorrelationFilter

logging.getLogger().addFilter(ProteanCorrelationFilter())
```

`Domain.init()` also detects a pre-configured root logger (handlers already
attached) and skips its auto-configuration in that case, so in many
embedded setups no env var is needed.

---

## Minimize noise in tests

In `conftest.py`:

```python
from protean.utils.logging import configure_for_testing

configure_for_testing()
```

This sets the root logger to WARNING and removes file handlers. Tests that
assert on log output with pytest's `caplog` fixture still work because
structlog writes to stdlib handlers.

---

## See also

- **[Logging reference](../../reference/logging.md)** — every config key, every
  framework logger, every event schema. Includes the `@log_method_call`
  decorator for handler-method entry/exit tracing at DEBUG.
- **[Logging concepts](../../concepts/observability/logging.md)** — wide events,
  query-oriented field design, backend selection, what Protean deliberately
  does not do.
- **[Correlation and Causation IDs](../observability/correlation-and-causation.md)** —
  how `correlation_id` propagates through commands, events, HTTP headers, OTel
  spans, and log records.
- **[OpenTelemetry Integration](./opentelemetry.md)** — distributed tracing
  and how `trace_id` / `span_id` reach log records.
- **[Production Deployment](./production-deployment.md)** — container logging,
  log forwarders, rotation, multi-worker hygiene.
