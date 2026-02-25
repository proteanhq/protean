# When to compose

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


The `Domain` class in Protean acts as a composition root. It manages external
dependencies and injects them into objects during application startup.

Your domain should be composed at the start of the application lifecycle — once,
before any request or task is handled. This means:

1. **Instantiate** the `Domain` and register elements (via decorators or
   manual registration).
2. **Initialize** the domain with `domain.init()` to activate adapters,
   validate element registration, and resolve dependencies.
3. **Push a domain context** before processing requests, so that
   `current_domain` is available throughout the call stack.

The exact integration point depends on your application framework.

## FastAPI (recommended)

Protean provides built-in middleware for FastAPI that handles domain context
management automatically:

```python
from fastapi import FastAPI
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)

from my_app.domain import domain

# Initialize the domain at module load time
domain.init()

app = FastAPI()

# Middleware pushes/pops domain context per request
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)

# Map domain exceptions to HTTP status codes
register_exception_handlers(app)
```

The middleware ensures every request runs inside a domain context, and the
exception handlers translate `ValidationError`, `ObjectNotFoundError`, etc.
into appropriate HTTP responses.

See [FastAPI Integration](../fastapi/index.md) for the full guide.

## Flask

For Flask, use `before_request` and `after_request` hooks to manage the
domain context:

```python hl_lines="29 33 35 38"
--8<-- "guides/compose-a-domain/019.py:full"
```

The domain is initialized once during `create_app()`, and the context is
pushed before each request and popped after.

## Console applications and scripts

In simple console applications, compose the domain in `main` and use
a `with` block for the domain context:

```python
from protean import Domain
from protean.fields import String

domain = Domain()

@domain.aggregate
class Task:
    title: String(max_length=200, required=True)

if __name__ == "__main__":
    domain.init()

    with domain.domain_context():
        repo = domain.repository_for(Task)
        repo.add(Task(title="Write documentation"))
```

## Background workers and the Protean server

The Protean server (`protean server`) handles domain composition internally.
You only need to point it at your domain module:

```shell
$ protean server --domain my_app.domain
```

The server initializes the domain, pushes a context, and manages the event
processing loop. See [Running the Server](../server/index.md) for details.

## Key principles

- **Compose once, early.** Call `domain.init()` at startup, not per-request.
  Initialization activates database connections, validates element
  registration, and is not designed to be called repeatedly.
- **Context per request.** Each request or task should run inside its own
  domain context (`domain.domain_context()`). The context makes
  `current_domain` available and manages the Unit of Work lifecycle.
- **Let the framework manage it.** Prefer framework-provided integration
  (FastAPI middleware, Flask hooks) over manual context management. This
  ensures contexts are properly cleaned up even when exceptions occur.
