# Logging

Protean ships with structured logging built on
[structlog](https://www.structlog.org/). A single call to `configure_logging()`
sets up environment-aware defaults so you get the right output format and log
level without manual configuration.

For basic server usage, see [Run the Server](./index.md). For production
deployment patterns, see [Production Deployment](./production-deployment.md).

## Quick start

```python
from protean.utils.logging import configure_logging, get_logger

configure_logging()  # Auto-detects environment

logger = get_logger(__name__)
logger.info("order_placed", order_id="ord-123", total=99.95)
```

## Environment-aware defaults

`configure_logging()` reads `PROTEAN_ENV` (or `ENV` / `ENVIRONMENT`) to pick
sensible defaults:

| Environment   | Log level | Output format           |
|---------------|-----------|-------------------------|
| `development` | DEBUG     | Colored console         |
| `production`  | INFO      | JSON                    |
| `staging`     | INFO      | JSON                    |
| `test`        | WARNING   | Colored console         |

Override the level with `PROTEAN_LOG_LEVEL` env var or the `level` parameter:

```python
configure_logging(level="DEBUG")  # Force DEBUG regardless of environment
```

Force a specific output format with the `format` parameter:

```python
configure_logging(format="json")     # JSON even in development
configure_logging(format="console")  # Colored console even in production
```

## Log levels

| Level | What's logged |
|-------|---------------|
| ERROR | Exceptions, failed processing |
| WARNING | Retries, DLQ moves, deprecation warnings |
| INFO | Startup, shutdown, batch summaries |
| DEBUG | Message details, position updates, config resolution |

## Rotating file handlers

For non-containerized deployments, enable rotating file handlers by passing
`log_dir`:

```python
configure_logging(
    log_dir="logs",
    log_file_prefix="myapp",  # Creates myapp.log and myapp_error.log
    max_bytes=10 * 1024 * 1024,  # 10 MB per file
    backup_count=5,
)
```

Containerized deployments typically log to stdout only (the default).

## Context variables

Enrich logs with request-scoped context that propagates across `await`
boundaries:

```python
from protean.utils.logging import add_context, clear_context

add_context(request_id="abc-123", customer_id="cust-001")
logger.info("processing")  # Includes request_id and customer_id

clear_context()  # Clean up at request end
```

## Method call tracing

The `@log_method_call` decorator logs entry, exit, and exceptions for handler
methods at DEBUG level:

```python
from protean.utils.logging import log_method_call

class PlaceOrderHandler:
    @log_method_call
    def handle(self, command):
        ...
```

## Noise suppression

`configure_logging()` automatically suppresses noisy third-party loggers
(urllib3, sqlalchemy, redis, elasticsearch, asyncio) and sets Protean framework
loggers to sensible levels. At DEBUG level, all Protean loggers are set to
DEBUG; at INFO and above, framework internals are set to WARNING.

## Test configuration

Minimize logging noise in test runs:

```python
# conftest.py
from protean.utils.logging import configure_for_testing

configure_for_testing()  # WARNING level, removes file handlers
```
