# Configuration

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Protean's configuration is managed through the Domain object, which can be configured in multiple ways:

## Direct Configuration

Pass a configuration dictionary when initializing the Domain object:

   ```python
   domain = Domain(config={'debug': True, 'testing': True})
   ```

## Configuration Files

Place configuration can be supplied in a TOML file in your project directory or up to two levels of parent directories.

Protean searches for configuration files in the following order:

1. `.domain.toml`
1. `domain.toml`
1. `pyproject.toml` (under the `[tool.protean]` section)

### Generating a new configuration file

When initializing a new Protean application using the [`new`](../cli/project/new.md) command, a `domain.toml` configuration file is automatically generated with sensible defaults.

A sample configuration file is below:

```toml
debug = true
testing = true
secret_key = "tvTpk3PAfkGr5x9!2sFU%XpW7bR8cwKA"
identity_strategy = "uuid"
identity_type = "string"
event_processing = "sync"
command_processing = "sync"
message_processing = "sync"

[databases.default]
provider = "memory"

[databases.memory]
provider = "memory"

[brokers.default]
provider = "inline"

[caches.default]
provider = "memory"

[event_store]
provider = "memory"

[custom]
foo = "bar"

[staging]
event_processing = "async"
command_processing = "sync"

[staging.databases.default]
provider = "sqlite"
database_url = "sqlite:///test.db"

[staging.brokers.default]
provider = "redis_pubsub"
URI = "redis://staging.example.com:6379/2"
TTL = 300

[staging.custom]
foo = "qux"

[prod]
event_processing = "async"
command_processing = "async"

[prod.databases.default]
provider = "postgresql"
database_url = "postgresql://postgres:postgres@localhost:5432/postgres"

[prod.brokers.default]
provider = "redis_pubsub"
URI = "redis://prod.example.com:6379/2"
TTL = 30

[prod.event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"

[prod.custom]
foo = "quux"

[prod.telemetry]
enabled = true
service_name = "my-service"
exporter = "otlp"
endpoint = "http://otel-collector:4317"
```

## Basic Configuration Parameters

### `debug`

Specifies if the application is running in debug mode.

*Do not enable debug mode when deploying in production.*

Default: `False`

### `testing`

Enable testing mode. Exceptions are propagated rather than handled by the
domain’s error handlers. Extensions may also change their behavior to
facilitate easier testing. You should enable this in your own tests.

Default: `False`

### `secret_key`

A secret key that will be used for security related needs by extensions or your
application. It should be a long random `bytes` or `str`.

You can generate a secret key with the following command:

```shell
> python -c 'import secrets; print(secrets.token_hex())'
c4bf0121035265bf44657217c33a7d041fe9e505961fc7da5d976aa0eaf5cf94
```

*Do not reveal your secret key when posting questions or committing code.*

### `identity_strategy`

The default strategy to use to generate an identity value. Can be overridden
at the [`Auto`](../fields/simple-fields.md#auto) field level.

Supported options are `uuid` and `function`.

If the `identity_strategy` is chosen to be a `function`, `identity_function`
has to be mandatorily specified during domain object initialization.

Default: `uuid`

### `identity_type`

The type of the identity value. Can be overridden
at the [`Auto`](../fields/simple-fields.md#auto) field level.

Supported options are `integer`, `string`, and `uuid`.

Default: `string`

### `command_processing`

Whether to process commands synchronously or asynchronously.

Supported options are `sync` and `async`.

Default: `sync`

### `event_processing`

Whether to process events synchronously or asynchronously.

Supported options are `sync` and `async`.

Default: `sync`

### `snapshot_threshold`

The threshold number of aggregate events after which a snapshot is created to
optimize performance.

Applies only when aggregates are event sourced.

Default: `10`

## Adapter Configuration

### `databases`

Database repositories are used to access the underlying data store for
persisting and retrieving domain objects.

They are defined in the `[databases]` section.

```toml hl_lines="1 4 7"
[databases.default]
provider = "memory"

[databases.memory]
provider = "memory"

[databases.sqlite]
provider = "sqlite"
database_uri = "sqlite:///test.db"
```

You can define as many databases as you need. The default database is identified
by the `default` key, and is used when you do not specify a database name when
accessing the domain.

The only other database defined by default is `memory`, which is the in-memory
stub database provider.

The persistence store defined here is then specified in the `provider` key of
aggregates and entities to assign them a specific database.

```python hl_lines="1"
@domain.aggregate(provider="sqlite")  # (1)
class User:
    name: String(max_length=50)
    email: String(max_length=254)
```

1. `sqlite` is the key of the database definition in the `[databases.sqlite]`
section.

SQLAlchemy providers (`postgresql`, `mssql`) accept pool tuning keys
directly on the `[databases.<name>]` block:

| Key | Default | Purpose |
|-----|---------|---------|
| `pool_size` | `5` | Base connections kept open per worker |
| `max_overflow` | `10` | Additional temporary connections beyond `pool_size` |
| `pool_recycle` | unset | Recycle connections older than N seconds |

Setting `pool_size` below `5` triggers a `LOW_POOL_SIZE` warning from
`protean check` (suppressed when `PROTEAN_ENV` is `development` or
`testing`).

Read more in [Adapters → Database](../adapters/database/index.md) or the
full catalogue in [Server Hardening reference](../server/hardening.md#connection-pools).

### `caches`

This section holds definitions for cache infrastructure.

```toml
[caches.default]
provider = "memory"

[caches.redis]
provider = "redis"
URI = "redis://127.0.0.1:6379/2"
TTL = 300
max_connections = 50
socket_timeout = 5
socket_connect_timeout = 5
retry_on_timeout = true
```

Default provider: `memory`

Redis caches forward `max_connections`, `socket_timeout`,
`socket_connect_timeout`, and `retry_on_timeout` to the underlying
`redis.ConnectionPool`.

Read more in [Adapters → Cache](../adapters/cache/index.md) section.

### `broker`

This section holds configurations for message brokers.

```toml
[brokers.default]
provider = "memory"

[brokers.redis]
provider = "redis_pubsub"
URI = "redis://127.0.0.1:6379/0"
IS_ASYNC = true
max_connections = 50
socket_timeout = 5
socket_connect_timeout = 5
retry_on_timeout = true
```

Default provider: `memory`

Redis brokers (`redis_pubsub`, `redis_stream`) forward the same pool
keys as the Redis cache to `redis.ConnectionPool`.

Read more in [Adapters → Broker](../adapters/broker/index.md) section.

### `event_store`

The event store that stores event and command messages is defined in this
section.

```toml
[event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"
max_connections = 20
```

Note that there can only be only event store defined per domain.

Default provider: `memory`

MessageDB forwards `max_connections` through `conn_info` to cap the
connection pool used for event reads and writes.

Read more in [Adapters → Event Store](../adapters/eventstore/index.md) section.

### `server`

This section configures the Protean server (async message processing engine).
It controls subscription behavior, outbox processing, and handler-specific
settings.

```toml
[server]
# Default subscription settings
default_subscription_type = "stream"      # "stream" or "event_store"
default_subscription_profile = "production"  # Profile for defaults
messages_per_tick = 100                   # Messages per processing cycle

# StreamSubscription defaults
[server.stream_subscription]
blocking_timeout_ms = 5000    # Blocking read timeout
max_retries = 3               # Retries before DLQ
retry_delay_seconds = 1       # Delay between retries
enable_dlq = true             # Enable dead letter queue

# EventStoreSubscription defaults
[server.event_store_subscription]
position_update_interval = 10  # Messages between position writes
max_retries = 3                # Retries before marking exhausted
retry_delay_seconds = 1        # Delay between recovery retries
enable_recovery = true         # Enable periodic recovery pass
recovery_interval_seconds = 30 # Interval between recovery sweeps

# BrokerSubscription defaults
[server.broker_subscription]
max_retries = 3               # Retries before DLQ
retry_delay_seconds = 1       # Delay between retries
enable_dlq = true             # Enable dead letter queue

# Version conflict auto-retry
# Retries ExpectedVersionError at the handler level before
# the error reaches the subscription retry/DLQ pipeline
[server.version_retry]
enabled = true               # Enable/disable auto-retry
max_retries = 3              # Fast retries before propagating
base_delay_seconds = 0.05    # 50ms initial backoff
max_delay_seconds = 1.0      # Cap backoff at 1 second

# DLQ maintenance (retention + alerting)
# Off by default; opt in by setting enabled = true.
[server.dlq]
enabled = false              # Master switch for the maintenance task
retention_hours = 168        # Trim DLQ entries older than this (default: 7 days)
alert_threshold = 100        # Warn when a DLQ stream reaches this depth
check_interval_seconds = 60  # How often the maintenance cycle runs
alert_callback = "myapp.alerts.notify_oncall"  # Optional dotted path, called on breach

# Kubernetes-compatible health HTTP server
# Enabled by default on port 8080; disable for tests or embedded use.
[server.health]
enabled = true               # Start the built-in health server
host = "0.0.0.0"             # Bind address
port = 8080                  # Listen port

# Handler-specific overrides
[server.subscriptions.OrderEventHandler]
profile = "fast"
messages_per_tick = 50
# Per-subscription DLQ overrides (inherit from [server.dlq] when unset)
dlq_retention_hours = 72
dlq_alert_threshold = 25

[server.subscriptions.InventoryProjector]
subscription_type = "event_store"
profile = "projection"
```

#### Subscription Profiles

Pre-configured settings for common scenarios:

| Profile | Type | Use Case |
| ------- | ---- | -------- |
| `production` | stream | High throughput with reliability |
| `fast` | stream | Low-latency processing |
| `batch` | stream | High-volume batch processing |
| `debug` | stream | Development and debugging |
| `projection` | event_store | Building read models |

Read more in [Server → Configuration](../server/configuration.md) section.

#### DLQ Maintenance

The `[server.dlq]` section configures a periodic maintenance task that
trims old DLQ entries and alerts when DLQ streams grow deep. It is
**disabled by default** — set `enabled = true` to activate it. Requires
a broker that implements the DLQ contract (currently Redis Streams).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch. When `true`, the Engine starts the maintenance task. |
| `retention_hours` | int | `168` | Trim DLQ entries older than this window (default 7 days). |
| `alert_threshold` | int | `100` | Emit a `WARNING` log and invoke `alert_callback` when a DLQ stream reaches this depth. |
| `check_interval_seconds` | int | `60` | How often the maintenance cycle runs. |
| `alert_callback` | str \| None | `None` | Dotted import path to a callable invoked on threshold breach. Signature: `(dlq_stream: str, depth: int, threshold: int) -> None`. Exceptions raised by the callback are caught and logged. |

Per-subscription overrides are available on each handler's
`[server.subscriptions.<HandlerName>]` block:

| Key | Type | Default | Description |
|---|---|---|---|
| `dlq_retention_hours` | int \| None | inherit | Override `retention_hours` for this subscription's DLQ stream only. |
| `dlq_alert_threshold` | int \| None | inherit | Override `alert_threshold` for this subscription's DLQ stream only. |

For the operational workflow — discover, inspect, replay, purge — see
[Dead Letter Queues](../../guides/server/dead-letter-queues.md).

#### Health Checks

The `[server.health]` section configures the built-in HTTP server used
for Kubernetes liveness and readiness probes. The server is **enabled by
default** on port `8080`.

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Start the health HTTP server. Set to `false` for tests or embedded deployments. |
| `host` | str | `"0.0.0.0"` | Bind address. |
| `port` | int | `8080` | Listen port. |

The server exposes `GET /healthz`, `GET /livez`, and `GET /readyz`. For
the probe response bodies, readiness semantics, and FastAPI router
factory, see
[Server Hardening reference](../server/hardening.md#health-checks).

### `outbox`

This section configures the transactional outbox pattern for reliable message
delivery. The outbox is automatically enabled when
`server.default_subscription_type` is set to `"stream"`. The legacy
`enable_outbox = true` flag still works for backward compatibility.

```toml
[server]
default_subscription_type = "stream"  # Enables outbox automatically

[outbox]
broker = "default"         # Target broker for publishing
messages_per_tick = 10     # Messages per processing cycle
tick_interval = 1          # Seconds between cycles

# Retry configuration
[outbox.retry]
max_attempts = 3           # Maximum retry attempts
base_delay_seconds = 60    # Initial retry delay
max_backoff_seconds = 3600 # Maximum retry delay
backoff_multiplier = 2     # Exponential backoff multiplier
jitter = true              # Add randomization to delays

# Cleanup configuration
[outbox.cleanup]
published_retention_hours = 168   # Keep published for 7 days
abandoned_retention_hours = 720   # Keep abandoned for 30 days
```

Read more in [Server → Outbox Pattern](../../concepts/async-processing/outbox.md) section.

### `telemetry`

This section configures OpenTelemetry distributed tracing and metrics.

```toml
[telemetry]
enabled = true
service_name = "my-service"
exporter = "otlp"
endpoint = "http://localhost:4317"

[telemetry.resource_attributes]
"deployment.environment" = "production"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | bool | `false` | Master switch for all OTel instrumentation |
| `service_name` | string | domain name | Populates the OTel `service.name` resource attribute |
| `exporter` | string | `"otlp"` | Span and metric exporter: `"otlp"` or `"console"` |
| `endpoint` | string | SDK default | OTLP collector endpoint (gRPC) |
| `resource_attributes` | table | `{}` | Additional OTel resource attributes |

When disabled (the default), all tracing and metrics are no-ops with zero
overhead. Requires `pip install "protean[telemetry]"`.

Read more in [OpenTelemetry Integration](../../guides/server/opentelemetry.md).

### `idempotency`

This section configures command idempotency deduplication. When configured with
a Redis instance, `domain.process()` can detect and deduplicate repeated
command submissions using caller-provided idempotency keys.

```toml
[idempotency]
redis_url = "redis://localhost:6379/5"  # Redis connection URL
ttl = 86400                              # Success entry TTL in seconds (default: 24 hours)
error_ttl = 60                           # Error entry TTL in seconds (default: 60s)
```

| Key | Description | Default |
| --- | ----------- | ------- |
| `redis_url` | Redis connection URL for the idempotency cache. When `None`, deduplication is disabled. | `None` |
| `ttl` | Time-to-live for successful idempotency entries (seconds). After expiry, the same key can be reused. | `86400` (24 hours) |
| `error_ttl` | Time-to-live for error entries (seconds). Short TTL allows retries after transient failures. | `60` |

Without `redis_url` configured, idempotency deduplication is disabled and
`domain.process()` works normally with no errors.

Read more in [Command Idempotency](../../patterns/command-idempotency.md).

## Custom Attributes

Custom attributes can be defined in toml under the `[custom]` section (or
`[tool.protean.custom]` if you are leveraging the `pyproject.toml` file).

Custom attributes are also made available as domain attributes.

```toml hl_lines="5"
debug = true
testing = true

[custom]
FOO = "bar"
```

```shell hl_lines="3-4 6-7"
In [1]: domain = Domain()

In [2]: domain.config["custom"]["FOO"]
Out[2]: 'bar'

In [3]: domain.FOO
Out[3]: 'bar'
```

## Multiple Environments

Most applications need more than one configuration. At the very least, there
should be separate configurations for production and for local development.
The `toml` configuration file can hold configurations for different
environments.

The current environment is gathered from an environment variable named
`PROTEAN_ENV`.

The string specified in `PROTEAN_ENV` is used as a qualifier in the
configuration.

```toml hl_lines="4 8"
[databases.default]
provider = "memory"

[staging.databases.default]
provider = "sqlite"
database_url = "sqlite:///test.db"

[prod.databases.default]
provider = "postgresql"
database_url = "postgresql://postgres:postgres@localhost:5432/postgres"
```

Protean has a default configuration with memory stubs that is overridden
by configurations in the `toml` file, which can further be over-ridden by an
environment-specific configuration, as seen above. There are two environment
specific settings above for databases - an `sqlite` db configuration for
`staging` and a `postgresql` db configuration for `prod`.

### Testing Overlays

A common use of environment overlays is **dual-mode testing** -- running the
same test suite against in-memory adapters for speed and real infrastructure
for confidence. Define a `[test]` overlay (the default for `pytest`) and a
`[memory]` overlay, then switch from the command line:

```toml
# Base configuration (development)
[databases.default]
provider = "postgresql"
database_uri = "postgresql://localhost/myapp_local"

[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"

# Test overlay: separate database, sync processing
[test]
testing = true
event_processing = "sync"

[test.databases.default]
database_uri = "postgresql://localhost/myapp_test"

# Memory overlay: all in-memory adapters, no Docker needed
[memory]
testing = true
event_processing = "sync"

[memory.databases.default]
provider = "memory"

[memory.event_store]
provider = "memory"

[memory.brokers.default]
provider = "inline"
```

```shell
pytest --protean-env memory   # Fast — in-memory, no infrastructure
pytest                        # Thorough — real adapters (PROTEAN_ENV=test)
```

Protean's pytest plugin sets `PROTEAN_ENV` before test collection via the
`--protean-env` option (default: `test`). See the
[Dual-Mode Testing](../../patterns/dual-mode-testing.md) pattern for the
full approach.
