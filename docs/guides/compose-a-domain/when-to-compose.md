# When to compose

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

The `Domain` class in Protean acts as a composition root. It sets up external
dependencies and injects them into objects during application startup.

Your domain should be composed at the start of the application lifecycle, once,
before any request or task is handled. This means:

1. **Instantiate** the `Domain`. Register its elements with decorators or by
   manual registration.
2. **Initialize** the domain with `domain.init()` to activate adapters,
   validate element registration, and resolve dependencies.
3. **Push a domain context** before processing requests, so that
   `current_domain` is available throughout the call stack.

The exact integration point depends on your application framework.

## FastAPI (recommended)

Protean provides built-in middleware for FastAPI that pushes and pops the
domain context for each request automatically. This example defines the domain
in the same file. In a larger app you would import it from its own module
instead:

```python
--8<-- "guides/compose-a-domain/when-to-compose/001.py:full"
```

The middleware runs every request inside a domain context. The exception
handlers translate `ValidationError`, `ObjectNotFoundError`, etc. into
appropriate HTTP responses.

See [FastAPI Integration](../fastapi/index.md) for the full guide.

## Flask

For Flask, use `before_request` and `teardown_request` hooks to push and pop
the domain context. Store the pushed context on Flask's `g`, so the teardown
hook pops that same context:

```python hl_lines="24 29 31 36"
--8<-- "guides/compose-a-domain/019.py:full"
```

The domain is initialized once during `create_app()`. The `before_request` hook
pushes the context before each request. The `teardown_request` hook pops it at
the end of the request, even if the request fails.

## Compose the domain in console applications and scripts

In simple console applications, compose the domain in a `main` function. Inside
that function, open the domain context with a `with` block:

```python
--8<-- "guides/compose-a-domain/when-to-compose/002.py:full"
```

## Run background workers with the Protean server

The Protean server (`protean server`) composes the domain internally. You only
need to point it at your domain module:

```shell
$ protean server --domain my_app.domain
```

The server initializes the domain and pushes a context. It then runs the event
processing loop. See [Running the Server](../server/index.md) for details.

## Follow these principles when you compose a domain

- **Compose once, early**: Call `domain.init()` at startup, not per-request.
  Initialization activates database connections and validates element
  registration. It is not designed to be called repeatedly.
- **Use one context per request**: Run each request or task inside its own
  domain context (`domain.domain_context()`). The context makes
  `current_domain` available and manages the Unit of Work lifecycle.
- **Let the framework manage it**: Prefer framework-provided integration
  (FastAPI middleware, Flask hooks) over manual context management. The
  framework integration then cleans up each context, even when an exception
  occurs.
