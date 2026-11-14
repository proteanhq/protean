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
| `protean db migrate` | Write a migration for the model's changes | No |
| `protean db upgrade` | Apply migrations to the database | No |
| `protean db downgrade` | Revert migrations in the database | No |
| `protean db check` | Report tables that differ from the table definitions | No |

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

## `protean db migrate`

Compares the domain's tables with the provider's database and writes a
migration script for the differences into `versions/`. Alembic's autogenerate
feature does the comparison.

```bash
protean db migrate -m "add price to product" --domain=my_domain
```

The command prints the path of the file it wrote. When the database already
matches the domain, it prints `No changes detected; no migration written.`,
writes no file and exits 0.

The migration covers the tables, columns, column types, indexes and unique
constraints of the provider's aggregates, entities and projections. An
event-sourced aggregate has no table, so a migration never creates one for it.
A table in the database that the domain does not declare is left alone: the
migration does not drop it. On SQLite, the migration changes a column by
copying the table, because SQLite cannot change most columns in place.

An index declared with `Index.from_sql` for the provider's database goes into
the migration that creates its table. A named one added to an existing table
gets a migration that creates it, and the downgrade drops it. An index declared
for another database is left out. Only the statement of an unnamed
`Index.from_sql` index gives its name, so on a table that declares one, the
migration drops no index. Drop an index you remove from such a table by hand.

The table copy on SQLite loses an expression index and the DESC order of an
index column. The migration rebuilds these indexes after each copy. In the
upgrade, it drops and creates again each named `Index.from_sql` index and each
index with a `desc=` column. The upgrade cannot rebuild an unnamed
`Index.from_sql` index, so a table copy can lose it. Give each one on SQLite a
`name=`. In the downgrade, it drops and creates again each index the table had
before the migration, from the statement SQLite stored for it.

Autogenerate does not detect these changes, so write the migration by hand:

- A changed `Index.from_sql` statement that keeps its name. The command
  compares these indexes by name only.
- A changed `where=` condition of a partial index.

Read each migration before you apply it. Alembic lists more changes it cannot
detect, such as a renamed table or column, in its
[autogenerate documentation](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect).

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--message`, `-m` | What the migration changes, used in its file name. Required. | |
| `--domain` | Domain module path | `.` (current directory) |
| `--directory` | Folder that holds the provider's migrations | `migrations` |

## `protean db upgrade`

Applies the migrations in `versions/` to the database, up to the revision
given. The revision defaults to `head`, the latest migration.

```bash
# Apply every migration
protean db upgrade --domain=my_domain

# Apply the next migration only
protean db upgrade +1 --domain=my_domain

# Print the SQL of every migration, without connecting to the database
protean db upgrade base:head --sql --domain=my_domain
```

With `--sql`, the command prints the SQL and does not connect to the database,
so it works while the database is unreachable. A range such as `base:head`
names where the SQL starts and ends.

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--directory` | Folder that holds the provider's migrations | `migrations` |
| `--sql` | Print the SQL instead of running it | `False` |

## `protean db downgrade`

Reverts migrations in the database, down to the revision given. The revision
has no default. Name it, for example `-1` for the last migration, a revision
id, or `base` to revert every migration.

```bash
# Revert the last migration
protean db downgrade -1 --domain=my_domain

# Print the SQL that reverts every migration, without connecting
protean db downgrade head:base --sql --domain=my_domain
```

With `--sql`, the revision must be a range such as `head:base`, because the
command does not read the database to learn where it is. Without a range, the
command stops with Alembic's message:
`downgrade with --sql requires <fromrev>:<torev>`.

Without a revision, the command takes the first word it does not know as the
revision. This lets `-1` through. The command also takes a mistyped option,
such as `--sqll`, as the revision. Alembic then reports an unknown revision. When a
revision is also given, as in `downgrade --sqll head:base`, the command stops
with an "unexpected extra argument" error and exits 2.

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--directory` | Folder that holds the provider's migrations | `migrations` |
| `--sql` | Print the SQL instead of running it | `False` |

The three commands read the provider's name from the `protean_provider` option
in `alembic.ini`, and make the same checks on the provider as
`protean db init`. They stop with a message when the folder has no
`alembic.ini`. For a second provider's folder, pass `--directory`:

```bash
protean db upgrade --directory=migrations/analytics
```

## `protean db check`

Compares the provider's database with the table definitions the domain
declares, and prints one line for each difference. It makes the same
comparison as `protean db migrate`. It writes no migration file, adds no row
to `alembic_version` and changes no table. Like `protean db migrate`, `upgrade`
and `downgrade`, it reads the provider's name from the `protean_provider`
option in `alembic.ini`.

```bash
protean db check --domain=my_domain
```

Each line names the operation a migration would need, then the table, then the
column, index or constraint where there is one:

```text
add_column order.discount
remove_column order.legacy_code
modify_type order.total
add_index order.ix_order_status
add_constraint order.sku
```

The operation says what differs:

- `add_table`, `add_column`, `add_index` and `add_constraint` name what the
  domain declares and the database lacks.
- `remove_column`, `remove_index` and `remove_constraint` name what a
  declared table has in the database and the domain does not declare.
- `modify_type` and `modify_nullable` name a column whose type or nullability
  differs.

A constraint with no name is named by its columns, such as
`add_constraint order.sku` for a unique field. A table in the database that
the domain does not declare is not reported. When the database and the domain
agree, the command prints `The database matches the table definitions.`

The command compares a database at the latest migration only. When the
database is at another revision, the command stops with a message that says
what to do: run `protean db upgrade`, run `protean db upgrade heads` when the
folder has more than one latest migration, or fix a database whose revision
the folder does not have.

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | The database matches the table definitions. |
| `1` | The database differs. The differences are on stdout. |
| `2` | The command could not compare. The message is on stderr. |

The command exits 2 when the domain does not load, when the provider fails
the checks of `protean db init`, when Alembic is not installed, when the
folder has no `alembic.ini`, when a file in the folder is broken, when the
database cannot be reached, and when the database is not at the latest
migration.

On SQLite, a database URI that names a missing file creates an empty file
when the domain connects. When the folder holds a migration, the command then
exits 2, because the empty database is not at the latest migration.

The command has two uses:

- In CI, run `protean db upgrade` on an empty database and then
  `protean db check`. Exit 1 means a model change has no migration. Write one
  with `protean db migrate`.
- Against a production database, `protean db check` finds a column, index or
  constraint that someone added or removed by hand, or a column whose type
  they changed. It does not see the changes that `protean db migrate` cannot
  detect, listed under [`protean db migrate`](#protean-db-migrate), or a
  changed server default.

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--directory` | Folder that holds the provider's migrations | `migrations` |

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
