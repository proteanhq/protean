# Configure for Production

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

This guide shows how to structure your `domain.toml` for multiple
environments, switch between in-memory and real adapters, and use
environment variables for secrets.

---

## Environment overlays

Protean uses the `PROTEAN_ENV` environment variable to select a
configuration overlay. Overlays are TOML sections that deeply merge
into the base configuration, overriding only the keys they specify.

```toml
# domain.toml

# Base configuration (recommended development overrides)
# Framework defaults are event_processing="async", command_processing="async"
debug = true
event_processing = "sync"
command_processing = "sync"

[databases.default]
provider = "memory"

[brokers.default]
provider = "inline"

[event_store]
provider = "memory"

# --- Production overlay: PROTEAN_ENV=production ---
[production]
debug = false
event_processing = "async"
command_processing = "async"

[production.databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"

[production.brokers.default]
provider = "redis"
URI = "${REDIS_URL}"

[production.event_store]
provider = "message_db"
database_uri = "${MESSAGEDB_URL}"

# --- Test overlay: PROTEAN_ENV=test (pytest default) ---
[test]
testing = true
event_processing = "sync"
command_processing = "sync"
```

Run with a specific environment:

```bash
# Development (base config, in-memory)
protean server --domain=my_domain

# Production
PROTEAN_ENV=production protean server --domain=my_domain

# Tests use PROTEAN_ENV=test automatically via Protean's pytest plugin
pytest
```

---

## Environment variable substitution

Use `${VAR_NAME}` syntax in TOML values. Provide a default with
`${VAR_NAME|default_value}`:

```toml
[production.databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL|postgresql://localhost:5432/myapp}"

[production.caches.default]
provider = "redis"
URI = "${REDIS_URL|redis://localhost:6379/2}"
TTL = 300
```

Protean raises `ConfigurationError` at startup if a required variable
is missing and no default is provided.

---

## Adapter selection

### Databases

```toml
# In-memory (default, no external dependencies)
[databases.default]
provider = "memory"

# PostgreSQL
[databases.default]
provider = "postgresql"
database_uri = "postgresql://user:pass@host:5432/db"

# SQLite
[databases.default]
provider = "sqlite"
database_uri = "sqlite:///path/to/db.sqlite3"

# Elasticsearch
[databases.default]
provider = "elasticsearch"
database_uri = "{'hosts': ['localhost']}"
```

### Brokers

```toml
# Inline (synchronous, no external service)
[brokers.default]
provider = "inline"

# Redis Streams (ordered, consumer groups, DLQ support)
[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"

# Redis Pub/Sub (simple fan-out)
[brokers.default]
provider = "redis_pubsub"
URI = "redis://localhost:6379/0"
```

### Event stores

```toml
# In-memory (default)
[event_store]
provider = "memory"

# Message DB (production, requires PostgreSQL + Message DB extension)
[event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"
```

### Caches

```toml
# In-memory (default)
[caches.default]
provider = "memory"

# Redis
[caches.default]
provider = "redis"
URI = "redis://localhost:6379/2"
TTL = 300
```

---

## Multiple databases

Register adapters under named keys to use different providers for
different aggregates:

```toml
[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"

[databases.analytics]
provider = "elasticsearch"
database_uri = "{'hosts': ['${ES_HOST|localhost}']}"
```

Then associate elements with specific databases in your domain:

```python
@domain.aggregate(provider="analytics")
class ProductSearch:
    ...
```

---

## Dual-mode testing

Define a `[memory]` overlay so the same test suite runs against both
in-memory and real adapters:

```toml
# Fast tests: PROTEAN_ENV=memory
[memory]
testing = true
event_processing = "sync"
command_processing = "sync"

[memory.databases.default]
provider = "memory"

[memory.brokers.default]
provider = "inline"

[memory.event_store]
provider = "memory"
```

Switch from the command line:

```bash
# Fast -- no Docker, no databases
pytest --protean-env memory

# Thorough -- real PostgreSQL, Redis, Message DB
pytest
```

See [Dual-Mode Testing](../../patterns/dual-mode-testing.md) for the
complete setup and CI configuration.

---

## Production checklist

- [ ] Set `PROTEAN_ENV=production` in your deployment environment
- [ ] Configure real database, broker, event store, and cache providers
- [ ] Use environment variables for all connection strings and secrets
- [ ] Set `event_processing = "async"` and `command_processing = "async"`
- [ ] Run `protean db setup --domain=my_domain` to create tables
- [ ] Configure server subscription type and worker count

For deployment patterns, see
[Production Deployment](../server/production-deployment.md).

---

!!! tip "See also"
    - [Configuration Reference](../../reference/configuration/index.md)
      -- Full list of all configuration parameters.
    - [Adapters Reference](../../reference/adapters/index.md)
      -- Provider-specific options and capabilities.
    - [Server Configuration](../../reference/server/configuration.md)
      -- Subscription profiles and handler settings.
