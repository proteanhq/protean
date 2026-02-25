# Chapter 8: Connecting a Real Database

In this chapter we will switch Bookshelf from in-memory storage to
PostgreSQL — with only a configuration change. Our domain code stays
exactly the same.

## Creating the Configuration File

Create a `domain.toml` file in your project directory:

```toml
debug = true
event_processing = "sync"
command_processing = "sync"

[databases.default]
provider = "postgresql"
database_uri = "postgresql://postgres:postgres@localhost:5432/bookshelf"
```

That is the only change needed. Every aggregate, command, event, and
projection we have built will now persist to PostgreSQL instead of
memory.

## Starting PostgreSQL

Start a PostgreSQL instance with Docker:

```shell
docker run -d --name bookshelf-db \
  -e POSTGRES_DB=bookshelf \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  postgres:15
```

## Running the Application

Run the same code we have been running throughout the tutorial:

```shell
$ python bookshelf.py
```

The output should look the same as before — but now the data is stored
in PostgreSQL. Protean creates the necessary tables automatically on
first run.

## Managing the Database Schema

Protean provides CLI commands to manage your database schema explicitly.
These are essential for production deployments where you want full
control over when tables are created or dropped:

```shell
# Create all tables (aggregates, entities, projections)
$ protean database setup --domain bookshelf

# Drop all tables (use with care!)
$ protean database drop --domain bookshelf

# Delete all data but keep the schema intact
$ protean database truncate --domain bookshelf
```

In development, Protean creates tables automatically. In production,
use `protean database setup` as part of your deployment process.

## Verifying Persistence

To confirm data is in the database, use the Protean shell:

```shell
$ protean shell --domain bookshelf
>>> repo = domain.repository_for(Book)
>>> books = repo.query.all()
>>> books.total
3
```

Or connect to PostgreSQL directly:

```shell
docker exec -it bookshelf-db psql -U postgres -d bookshelf -c "SELECT title FROM book;"
```

!!! tip "Production Credentials"
    For production, use environment variables instead of hardcoded
    credentials: `database_uri = "${DATABASE_URL}"`. See
    [Configuration](../../../reference/configuration/index.md) for details on
    environment variables, multiple databases, and per-environment
    settings.

## What We Built

- A **`domain.toml`** configuration file that switches the database
  from memory to PostgreSQL.
- **Zero code changes** — the same domain logic runs against any
  database adapter.
- **`protean database setup/drop/truncate`** — CLI commands for schema
  management.

Our domain logic is now decoupled from storage. In the next chapter,
we will organize the growing codebase into a proper project structure.

## Next

[Chapter 9: Structuring the Project →](09-project-structure.md)
