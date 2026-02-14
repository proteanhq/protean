# Chapter 12: Configuration and Real Databases

Everything so far has run in-memory — great for learning, but it
disappears when the process exits. In this chapter we connect Bookshelf
to a real database using Protean's configuration system.

## The Configuration System

Protean reads configuration from TOML files in your project directory.
It searches for these files in order:

1. `.domain.toml` — private, gitignored settings
2. `domain.toml` — project-level settings
3. `pyproject.toml` — under the `[tool.protean]` section

Create a `domain.toml` in your Bookshelf project:

```toml
debug = true
testing = true
identity_strategy = "uuid"
identity_type = "string"
event_processing = "sync"
command_processing = "sync"

[databases.default]
provider = "memory"
```

This is what Protean uses by default. Let's change it to use a real
database.

## Configuring PostgreSQL

To switch to PostgreSQL, update the database configuration:

```toml
debug = true
event_processing = "sync"
command_processing = "sync"

[databases.default]
provider = "postgresql"
database_uri = "postgresql://postgres:postgres@localhost:5432/bookshelf"
```

That is all the code change needed. Your domain code stays exactly the
same — aggregates, commands, events, projections — none of it changes.

### Starting PostgreSQL with Docker

Protean provides a Docker Compose setup. If you are working within the
Protean source:

```shell
make up
```

Or start PostgreSQL manually:

```shell
docker run -d --name bookshelf-db \
  -e POSTGRES_DB=bookshelf \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  postgres:15
```

### Environment Variable Substitution

For production, avoid hardcoding credentials. Use environment variables:

```toml
[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"
```

Protean replaces `${DATABASE_URL}` with the environment variable value.

## Multiple Databases

You can define multiple databases and assign aggregates to specific ones:

```toml
[databases.default]
provider = "postgresql"
database_uri = "postgresql://localhost:5432/bookshelf"

[databases.search]
provider = "elasticsearch"
URI = "localhost:9200"
```

Then assign aggregates:

```python
@domain.aggregate(provider="default")  # PostgreSQL
class Book:
    ...

@domain.projection(provider="search")  # Elasticsearch
class BookCatalog:
    ...
```

This lets you use the best storage technology for each use case —
relational for aggregates, search-optimized for projections.

## Database Models

By default, Protean auto-generates database models from your aggregates.
For most cases, this works perfectly. But when you need custom table
mappings, define a **database model**:

```python
@domain.database_model(part_of=Book)
class BookDatabaseModel:
    title: String(max_length=200)
    author: String(max_length=150)
    isbn: String(max_length=13)
    price_amount: Float()
    price_currency: String(max_length=3)

    class Meta:
        schema_name = "books"

    @classmethod
    def from_entity(cls, entity):
        return cls(
            title=entity.title,
            author=entity.author,
            isbn=entity.isbn,
            price_amount=entity.price.amount if entity.price else None,
            price_currency=entity.price.currency if entity.price else None,
        )

    def to_entity(self):
        return Book(
            title=self.title,
            author=self.author,
            isbn=self.isbn,
            price=Money(amount=self.price_amount, currency=self.price_currency),
        )
```

Database models give you full control over:

- Table names (`schema_name`)
- Column mappings (flattening value objects into columns)
- Custom serialization/deserialization

!!! tip "When to Customize"
    Use auto-generated models by default. Customize only when you need
    specific table structures, column names, or legacy database
    compatibility.

## Environment-Based Configuration

Real projects need different settings per environment. Protean supports
this through environment sections:

```toml
# Default (development)
event_processing = "sync"
command_processing = "sync"

[databases.default]
provider = "memory"

# Staging
[staging]
event_processing = "async"

[staging.databases.default]
provider = "postgresql"
database_uri = "${STAGING_DB_URL}"

# Production
[prod]
event_processing = "async"
command_processing = "async"

[prod.databases.default]
provider = "postgresql"
database_uri = "${PROD_DB_URL}"
```

Set the `PROTEAN_ENV` environment variable to select the configuration:

```shell
export PROTEAN_ENV=prod
python bookshelf.py
```

Protean loads the base configuration first, then overlays the
environment-specific settings.

## Summary

In this chapter you learned:

- **`domain.toml`** configures databases, brokers, event stores, and
  other infrastructure.
- Switching from in-memory to **PostgreSQL** requires only a config
  change — domain code stays the same.
- **Environment variables** (`${VAR}`) keep secrets out of config files.
- **Multiple databases** can be configured and assigned to specific
  aggregates or projections.
- **Database models** provide custom table mappings when needed.
- **Environment sections** (`[staging]`, `[prod]`) support different
  configurations per deployment.

The domain logic is now decoupled from storage — the same code runs
against memory, PostgreSQL, or Elasticsearch depending on configuration.

In the next chapter, we will switch from synchronous to **asynchronous
event processing** using message brokers and the Protean server.

## Next

[Chapter 13: Async Processing and the Server →](13-async-processing.md)
