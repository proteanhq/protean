# Chapter 9: Structuring the Project

Our `bookshelf.py` file has grown to hundreds of lines — aggregates,
value objects, commands, handlers, events, projections, and projectors
all in one file. Before we add an API layer and more features, we need
a proper project structure.

## Why Restructure Now?

A single file works for learning, but a real application needs
separation:

- Commands and handlers grow independently of the domain model.
- Projections and projectors change at a different pace than aggregates.
- An API layer needs clean imports from organized modules.
- Tests mirror the source structure.

## The Target Layout

```
bookshelf/
  __init__.py          # Domain instance
  models.py            # Aggregates, entities, value objects
  commands.py          # Commands
  events.py            # Domain events
  handlers.py          # Command handlers and event handlers
  projections.py       # Projections and projectors
domain.toml            # Configuration
tests/
  conftest.py
  test_commands.py
  test_invariants.py
```

## Creating the Package

### The Domain Instance

The domain lives in `bookshelf/__init__.py`:

```python
--8<-- "guides/getting-started/tutorial/ch09.py:domain_init"
```

### Models

Aggregates, entities, and value objects go in `bookshelf/models.py`:

```python
--8<-- "guides/getting-started/tutorial/ch09.py:models"
```

### Events

Domain events go in `bookshelf/events.py`:

```python
--8<-- "guides/getting-started/tutorial/ch09.py:events"
```

### Commands

Commands go in `bookshelf/commands.py`:

```python
--8<-- "guides/getting-started/tutorial/ch09.py:commands"
```

### Handlers

Command handlers and event handlers go in `bookshelf/handlers.py`:

```python
--8<-- "guides/getting-started/tutorial/ch09.py:handlers"
```

### Projections

Projections and projectors go in `bookshelf/projections.py`:

```python
--8<-- "guides/getting-started/tutorial/ch09.py:projections"
```

## Domain Auto-Discovery

Notice that we no longer pass `traverse=False` to `domain.init()`. With
a proper package structure, Protean auto-discovers all domain elements
by scanning the package:

```python
# In __init__.py
domain.init()  # traverse=True by default — scans bookshelf/ for elements
```

This finds all `@domain.aggregate`, `@domain.command`, `@domain.event`,
etc. decorators across every module in the `bookshelf/` package.

## The Configuration File

Move `domain.toml` to the project root (next to the `bookshelf/`
package):

```toml
debug = true
event_processing = "sync"
command_processing = "sync"

[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL|postgresql://postgres:postgres@localhost:5432/bookshelf}"
```

## Using CLI Tools

With a package structure, Protean CLI tools need to know where the
domain lives. Use the `--domain` flag:

```shell
$ protean shell --domain bookshelf
>>> from bookshelf.models import Book
>>> domain.repository_for(Book).query.all().total
3
```

Or set the `PROTEAN_DOMAIN` environment variable so you don't have to
pass `--domain` every time:

```shell
$ export PROTEAN_DOMAIN=bookshelf
$ protean shell
$ protean database setup
```

## Verifying the Structure

Run the application to make sure everything still works:

```shell
$ python -c "from bookshelf import domain; domain.init(); print('Domain initialized with', len(domain.registry._elements), 'elements')"
```

All domain elements should be discovered and registered just as before.

## What We Built

- A proper **Python package** with separate modules for models, commands,
  events, handlers, and projections.
- **Domain auto-discovery** — `domain.init()` scans the package
  automatically.
- **CLI integration** with `--domain` and `PROTEAN_DOMAIN`.
- The same functionality as before, but organized for growth.

In the next chapter, we will add a FastAPI web layer to expose our
domain through HTTP endpoints.

## Next

[Chapter 10: Exposing the Domain Through an API →](10-api.md)
