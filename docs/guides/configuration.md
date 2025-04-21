# Configuration

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

When initializing a new Protean application using the [`new`](./cli/new.md) command, a `domain.toml` configuration file is automatically generated with sensible defaults.

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
provider = "redis"
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
provider = "redis"
URI = "redis://prod.example.com:6379/2"
TTL = 30

[prod.event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"

[prod.custom]
foo = "quux"
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
at the [`Auto`](./domain-definition/fields/simple-fields.md#auto) field level.

Supported options are `uuid` and `function`.

If the `identity_strategy` is chosen to be a `function`, `identity_function`
has to be mandatorily specified during domain object initialization.

Default: `uuid`

### `identity_type`

The type of the identity value. Can be overridden
at the [`Auto`](./domain-definition/fields/simple-fields.md#auto) field level.

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
    name = String(max_length=50)
    email = String(max_length=254)
```

1. `sqlite` is the key of the database definition in the `[databases.sqlite]`
section.

Read more in [Adapters → Database](../adapters/database/index.md) section.

### `caches`

This section holds definitions for cache infrastructure.

```toml
[caches.default]
provider = "memory"

[caches.redis]
provider = "redis"
URI = "redis://127.0.0.1:6379/2"
TTL = 300
```

Default provider: `memory`

Read more in [Adapters → Cache](../adapters/cache/index.md) section.

### `broker`

This section holds configurations for message brokers.

```toml
[brokers.default]
provider = "memory"

[brokers.redis]
provider = "redis"
URI = "redis://127.0.0.1:6379/0"
IS_ASYNC = true
```

Default provider: `memory`

Read more in [Adapters → Broker](../adapters/broker/index.md) section.

### `event_store`

The event store that stores event and command messages is defined in this
section.

```toml
[event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"
```

Note that there can only be only event store defined per domain.

Default provider: `memory`

Read more in [Adapters → Event Store](../adapters/eventstore/index.md) section.

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
