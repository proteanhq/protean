# Configuration

## Primary Configuration Attributes

### `environment`

The `environment` attribute specifies the current running environment of the
application. By default, the environment is `development`. The current
environment can be gathered from an environment variable called `PROTEAN_ENV`.

Protean recognizes `development` and `production` environments, but additional
environments such as `pre-prod`, `staging`, and `testing` can be specified as
needed.

- **Default Value**: `development`
- **Environment Variable**: `PROTEAN_ENV`
- **Examples**:
  - `development`
  - `production`
  - `pre-prod`
  - `staging`
  - `testing`

### `debug`

### `testing`

### `secret_key`

## Domain Configuration Attributes

### `identity_strategy`

### `identity_type`

### `command_processing`

### `event_processing`

### `snapshot_threshold`

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
stub database provider. You can name all other database definitions as
necessary.

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

### `cache`

### `broker`

### `event_store`

## Custom Attributes

Custom attributes can be defined in toml under the `[custom]` section (or
`[tool.protean.custom]` if you are leveraging the `pyproject.toml` file).

Custom attributes are also made available on the domain object directly.

```toml hl_lines="5"
debug = true
testing = true

[custom]
FOO = "bar"
```

```shell hl_lines="3-4 6-7"
In [1]: domain = Domain(__file__)

In [2]: domain.config["custom"]["FOO"]
Out[2]: 'bar'

In [3]: domain.FOO
Out[3]: 'bar'
```
