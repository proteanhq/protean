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

Creates only the outbox tables. This is useful when migrating an existing domain
from event-store subscriptions to stream subscriptions, where the main database
tables already exist but the outbox table does not.

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
