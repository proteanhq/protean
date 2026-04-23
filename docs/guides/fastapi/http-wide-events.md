# HTTP wide events

!!! abstract "What is a wide event?"
    A **wide event** is one rich, structured log line per unit of work
    (a handled message, an HTTP request) carrying every field an operator
    might want to query on — rather than a stream of thin events you
    later have to join by correlation ID. The pattern comes from Jamie
    Brandon's [*Logging Sucks, So Use Wide Events*](https://loggingsucks.com)
    and Stripe's [canonical log lines](https://brandur.org/canonical-log-lines).
    See the [logging concept page](../../concepts/observability/logging.md#the-wide-event-pattern)
    for the full rationale.

`DomainContextMiddleware` emits one **wide event per HTTP request** on
the `protean.access.http` logger. The event carries the request envelope
(method, path, status, duration), the commands dispatched during the
request, a `request_id`, and a `correlation_id` that links the HTTP layer
to the domain-layer [`protean.access`](../server/logging.md) events
produced by the handler mixin.

This guide covers wiring, configuration, and enrichment. For the full
field schema see the [logging reference](../../reference/logging.md#proteanaccesshttp);
for the design rationale behind the two-layer split see the
[logging concepts page](../../concepts/observability/logging.md#two-layers-of-wide-events).

---

## What you get out of the box

As soon as you install `DomainContextMiddleware`, every HTTP request
produces a wide event like this (production JSON renderer):

```json
{
  "event": "access.http_completed",
  "level": "info",
  "logger": "protean.access.http",
  "timestamp": "2026-04-23T10:15:32.401Z",
  "http_method": "POST",
  "http_path": "/orders",
  "http_status": 201,
  "http_duration_ms": 18.92,
  "route_name": "place_order",
  "route_pattern": "/orders",
  "request_id": "req-7a2b4f",
  "correlation_id": "req-abc-123",
  "commands_dispatched": ["PlaceOrder"],
  "commands_dispatched_count": 1,
  "client_ip": "203.0.113.42",
  "user_agent": "MyApp/2.3 (iOS 17.2)"
}
```

Level ladders match severity — INFO for 2xx/3xx, WARNING for 4xx, ERROR
for 5xx or unhandled exceptions. A 5xx event carries `error_type` and
`error_message` plus the inlined traceback under `exception`.

---

## Enable it

`DomainContextMiddleware` emits HTTP wide events by default once
`domain.init()` has auto-configured logging:

```python
from fastapi import FastAPI
from protean.integrations.fastapi import DomainContextMiddleware

from my_app.identity import identity_domain
from my_app.catalogue import catalogue_domain

app = FastAPI()
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/customers": identity_domain,
        "/products": catalogue_domain,
    },
)
```

No other wiring is required. The logger name (`protean.access.http`) is
pre-configured at INFO by `Domain.configure_logging()`.

---

## Tune via `domain.toml`

```toml
[logging.http]
enabled = true
exclude_paths = ["/healthz", "/readyz", "/metrics"]
log_request_headers = false
log_response_headers = false
```

| Key | Default | Effect |
|-----|---------|--------|
| `enabled` | `true` | Master switch. Set to `false` to suppress HTTP wide events entirely. |
| `exclude_paths` | `[]` | Paths (exact match) that never emit. Use for liveness probes and high-volume health endpoints. |
| `log_request_headers` | `false` | Include the full request headers dict. Redaction still applies to tokens and cookies. |
| `log_response_headers` | `false` | Include the full response headers dict. Redaction still applies. |

See the [reference](../../reference/logging.md#logginghttp) for full
schema details.

### Override per-middleware

Explicit constructor arguments on `DomainContextMiddleware` override the
domain config for that middleware instance:

```python
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/api": my_domain},
    emit_http_wide_event=True,
    exclude_paths=["/api/internal/ping"],
    log_request_headers=True,
)
```

Passing `None` (the default) defers to `[logging.http]`. Passing an
explicit `True`/`False` or list wins over the config.

---

## Enrich with business context

Use the same `bind_event_context()` API as domain handlers. Bindings
made inside a FastAPI endpoint flow onto both the HTTP wide event *and*
any domain wide events emitted by commands dispatched during the
request:

```python
from fastapi import APIRouter
from protean.utils.globals import current_domain
from protean.utils.logging import bind_event_context

router = APIRouter()

@router.post("/orders")
async def place_order(request: PlaceOrderRequest, user=Depends(get_user)):
    bind_event_context(
        user_id=user.id,
        user_tier=user.tier,
        device_platform=request.device_platform,
    )
    current_domain.process(PlaceOrder(**request.model_dump()))
    return {"ok": True}
```

The resulting `access.http_completed` event now carries `user_id`,
`user_tier`, and `device_platform` alongside the framework fields. So
does the `access.handler_completed` event emitted by `PlaceOrderHandler`.

### Framework fields are protected

Keys that collide with framework-reserved HTTP fields (`http_method`,
`http_status`, `request_id`, etc.) or stdlib `LogRecord` attributes are
dropped before emission — application code cannot accidentally (or
intentionally) overwrite `http_status=200` with a value of its own. See
the [concept page](../../concepts/observability/logging.md#how-protean-builds-wide-events-automatically)
for why.

---

## Correlate HTTP and domain events

Every HTTP response echoes `X-Request-ID` back to the caller — even on
synthesised 500s. Copy that value into your log aggregator to pull the
full thread for a single request:

```logql
{logger=~"protean.access.*"}
  | json
  | request_id="req-7a2b4f"
```

One HTTP event plus every domain event emitted during the same request.
If your incoming client already sends `X-Request-ID`, the middleware
reuses it (truncated to 200 characters for safety); otherwise it
generates a hex UUID.

For multi-service setups, pass through `X-Correlation-ID` as well — the
middleware extracts it first, falling back to `X-Request-ID`. See
[Correlation and Causation IDs](../observability/correlation-and-causation.md)
for the full propagation story.

---

## Combine with tail sampling

HTTP requests can have much higher volume than domain operations
(scanners, health checks, bots). The `protean.access.http` logger is
nested under `protean.access`, so any
[tail sampling config](../server/logging.md#control-wide-event-volume-with-tail-sampling)
you enable on `protean.access` automatically applies to HTTP wide
events too.

A common production shape:

```toml
[logging.sampling]
enabled = true
default_rate = 0.01          # keep 1% of happy-path requests
always_keep_errors = true    # all 5xx and unhandled exceptions
always_keep_slow = true      # any handler over the threshold
critical_streams = ["Payment*", "Auth*"]
```

Combined with `[logging.http].exclude_paths` for liveness probes, this
typically brings HTTP wide event volume down by 95 %+ without losing
any error or performance signal.

---

## See also

- **[Logging guide](../server/logging.md)** — configuring the framework
  logger, `bind_event_context()` on domain handlers.
- **[Logging reference](../../reference/logging.md#proteanaccesshttp)** —
  full field schema for `access.http_completed` and `access.http_failed`.
- **[Logging concepts](../../concepts/observability/logging.md#two-layers-of-wide-events)** —
  why the HTTP and domain layers are separate loggers.
- **[Correlation and Causation IDs](../observability/correlation-and-causation.md)** —
  how `correlation_id` propagates across HTTP headers, commands, events,
  and log records.
- **[ADR-0010: Logging overhaul and wide event architecture](../../adr/0010-logging-overhaul-and-wide-event-architecture.md)** —
  design rationale for the two-layer split and the `bind_event_context`
  dual-write.
