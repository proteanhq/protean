# When to compose

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

The `Domain` class in Protean acts as a composition root. It manages external
dependencies and injects them into objects during application startup.

Your domain should be composed at the start of the application lifecycle, once,
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
management automatically. This example defines the domain in the same file. In
a larger app you would import it from its own module instead:

```python
--8<-- "guides/compose-a-domain/when-to-compose/001.py:full"
```

The middleware ensures every request runs inside a domain context, and the
exception handlers translate `ValidationError`, `ObjectNotFoundError`, etc.
into appropriate HTTP responses.

See [FastAPI Integration](../fastapi/index.md) for the full guide.

## Flask

For Flask, use `before_request` and `teardown_request` hooks to manage the
domain context. Keep the context you push on Flask's `g`, so the teardown hook
pops that same context:

```python hl_lines="24 29 31 36"
--8<-- "guides/compose-a-domain/019.py:full"
```

The domain is initialized once during `create_app()`. The context is pushed
before each request and popped when the request ends, even if it fails.

## Console applications and scripts

In simple console applications, compose the domain in a `main` function and use
a `with` block for the domain context:

```python
--8<-- "guides/compose-a-domain/when-to-compose/002.py:full"
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

- **Compose once, early**: Call `domain.init()` at startup, not per-request.
  Initialization activates database connections, validates element
  registration, and is not designed to be called repeatedly.
- **Context per request**: Each request or task should run inside its own
  domain context (`domain.domain_context()`). The context makes
  `current_domain` available and manages the Unit of Work lifecycle.
- **Let the framework manage it**: Prefer framework-provided integration
  (FastAPI middleware, Flask hooks) over manual context management. This
  ensures contexts are properly cleaned up even when exceptions occur.
