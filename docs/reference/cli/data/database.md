# `protean db`

The `protean db` command group manages database schema and data for a Protean
domain. All commands accept a `--domain` option to specify the domain module
path (defaults to the current directory).

## Commands

| Command | Description | Confirmation |
|---------|-------------|-------------|
| `protean db setup` | Create all database tables | No |
| `protean db drop` | Drop all database tables | Yes |
| `protean db truncate` | Delete all rows, preserve schema | Yes |
| `protean db setup-outbox` | Create only outbox tables | No |
| `protean db init` | Create the migrations folder for one provider | No |

## `protean db setup`

Creates all database artifacts (tables, indexes, constraints) for every
configured provider. This includes tables for aggregates, entities, projections,
and outbox (if enabled).

```bash
protean db setup --domain=my_domain
```

Run this before starting the server for the first time, or after modifying your
domain model.

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |

## `protean db drop`

Drops all database tables and schema objects for every configured provider.

```bash
# Interactive — prompts for confirmation
protean db drop --domain=my_domain

# Non-interactive — skips confirmation
protean db drop --domain=my_domain --yes
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--yes`, `-y` | Skip confirmation prompt | `False` |

## `protean db truncate`

Deletes all rows from every table while preserving the schema. This is faster
than dropping and recreating tables, and is useful for resetting data between
test runs or during development.

```bash
# Interactive — prompts for confirmation
protean db truncate --domain=my_domain

# Non-interactive — skips confirmation
protean db truncate --domain=my_domain --yes
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--yes`, `-y` | Skip confirmation prompt | `False` |

## `protean db setup-outbox`

Creates only the outbox tables. Use this command when you migrate an existing
domain from event-store subscriptions to stream subscriptions. In that case the
main database tables already exist, but the outbox table does not.

```bash
protean db setup-outbox --domain=my_domain
```

This command requires that the outbox is enabled in your configuration
(`default_subscription_type = "stream"`). If the outbox is not enabled, the
command exits with an error.

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |

## `protean db init`

Creates the folder that holds the schema migrations of one database provider.
A migration is a versioned script that changes the schema. Protean runs them
through [Alembic](https://alembic.sqlalchemy.org/), which the `postgresql`,
`postgresql-psycopg2`, `sqlite`, `mssql` and `mysql` extras install.

```bash
protean db init --domain=my_domain
```

The command writes these files into the folder:

| Path | Content |
|------|---------|
| `alembic.ini` | Alembic's settings. `protean_domain` records the domain path, `protean_provider` the provider name and `protean_root` the folder the command ran in. |
| `env.py` | Two lines that call Protean's `run_migrations`. It loads the domain and runs the migrations on the provider's database. |
| `script.py.mako` | The template for new migration scripts. |
| `versions/` | An empty folder for the migration scripts. |

Plain `alembic` commands work on the folder:

```bash
alembic -c migrations/alembic.ini current
alembic -c migrations/alembic.ini stamp head
```

The commands work from any folder. Protean resolves a relative
`protean_domain`, and a relative SQLite database URL, from `protean_root`.
`protean_domain` records the `--domain` value, or the `PROTEAN_DOMAIN`
environment variable when it is set. When `PROTEAN_DOMAIN` is set during a
plain `alembic` run, its value is used in place of `protean_domain`.

A plain `alembic` run makes the same checks on the provider as
`protean db init`.

The command refuses, and writes nothing, when:

- The provider does not declare the `SCHEMA_MIGRATIONS` capability. The
  memory and Elasticsearch providers do not. The message lists the configured
  providers that do.
- The provider sets `managed = false`. Protean does not change the schema of
  an unmanaged database.
- The folder exists and is not empty, or a file sits at its path. An existing
  empty folder is used.

It also stops when `--provider` names a provider the domain does not
configure, when Alembic is not installed, and when the folder cannot be
written. The message for a missing Alembic names the extra to install. When a
write fails part-way, the command removes the files it wrote.

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--provider` | Name of the database provider | `default` |
| `--directory` | Folder to create the migrations in | `migrations` |

Each provider gets its own folder. For a second provider, pass both options:

```bash
protean db init --provider=analytics --directory=migrations/analytics
```

## Domain Discovery

All `protean db` commands use the same domain discovery mechanism as
`protean server`. The `--domain` option accepts:

- A Python module path: `my_package.domain`
- A file path: `src/my_domain.py`
- A module with instance name: `my_domain:custom_domain`
- `.` (default): Searches the current directory

See [Domain Discovery](../project/discovery.md) for the full resolution logic.

## Examples

### Initial Setup

```bash
# Create all tables for a new project
protean db setup --domain=my_package.domain
```

### Reset Data During Development

```bash
# Delete all data without dropping schema
protean db truncate --domain=my_package.domain --yes
```

### Migrate to Stream Subscriptions

```bash
# Enable stream subscriptions in domain.toml:
# [server]
# default_subscription_type = "stream"

# Create only the outbox table (other tables already exist)
protean db setup-outbox --domain=my_package.domain
```

### Full Reset

```bash
# Drop everything and start fresh
protean db drop --domain=my_package.domain --yes
protean db setup --domain=my_package.domain
```
