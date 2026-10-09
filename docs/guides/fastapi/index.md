# FastAPI Integration

Protean provides integration utilities for
[FastAPI](https://fastapi.tiangolo.com/) applications. These live in the
`protean.integrations.fastapi` package and cover two concerns:

1. **Domain context middleware**: Automatically push the correct Protean
   domain context per HTTP request.
2. **Exception handlers**: Map Protean domain exceptions to standard HTTP
   error responses.

---

## Domain context middleware

Every Protean operation needs an active domain context. In a FastAPI
application, each HTTP request should run inside the context of the domain
it belongs to. `DomainContextMiddleware` handles this automatically by
matching the request URL path to a `Domain` instance.

### Basic setup

```python
--8<-- "guides/fastapi/index/001.py:basic"
```

With this configuration:

- Requests to `/customers/...` run inside `identity_domain.domain_context()`
- Requests to `/products/...` run inside `catalogue_domain.domain_context()`
- Requests that don't match any prefix (e.g. `/health`) pass through without
  a domain context, suitable for health checks, docs, and static assets.

### Longest-prefix matching

When multiple prefixes overlap, the longest match wins:

```python
--8<-- "guides/fastapi/index/002.py:longest-prefix"
```

A request to `/api/v2/items` matches `/api/v2` (the longer prefix) and uses
`v2_domain`. A request to `/api/v1/items` matches `/api` and uses
`core_domain`.

### Custom resolver

For more advanced routing logic (e.g. tenant-based, header-based, or
database-driven resolution), provide a `resolver` callable instead of a
static map:

```python
--8<-- "guides/fastapi/index/003.py:resolver"
--8<-- "guides/fastapi/index/003.py:register"
```

When a resolver is provided, `route_domain_map` is ignored. Returning `None`
from the resolver means the request proceeds without a domain context.

### Single-domain applications

For applications with only one domain, you can map the root prefix:

```python
--8<-- "guides/fastapi/index/004.py:single-domain"
```

### Correlation ID header

The middleware automatically extracts `X-Correlation-ID` (falling back to
`X-Request-ID`) from incoming request headers and makes it available as the
default correlation ID for command processing. The response always includes an
`X-Correlation-ID` header reflecting the ID that was used, from the request header, an
explicit `domain.process()` parameter, or an auto-generated UUID.

This means no manual header extraction is needed in your endpoints:

```python
--8<-- "guides/fastapi/index/006.py:endpoint"
```

For the full story on how correlation IDs propagate through commands, events,
logging, and OTEL spans, see
[Correlation and Causation IDs](../observability/correlation-and-causation.md).

### HTTP wide event logging

`DomainContextMiddleware` also emits one **wide event per HTTP request**
on the `protean.access.http` logger, request envelope, commands dispatched during the request,
`request_id`, and `correlation_id` shared with any domain-layer wide events. See the dedicated [HTTP
wide events guide](./http-wide-events.md) for configuration, enrichment, and
tail sampling.

---

## Exception handlers

`register_exception_handlers` maps Protean domain exceptions to appropriate
HTTP status codes so that your endpoint code can raise domain exceptions
directly without manual try/except blocks.

### Setup

```python
--8<-- "guides/fastapi/index/005.py:setup"
```

### Exception mapping

| Protean exception     | HTTP status | Response body                   |
|-----------------------|:-----------:|---------------------------------|
| `ValidationError`     | 400         | `{"error": exc.messages}`       |
| `InvalidDataError`    | 400         | `{"error": exc.messages}`       |
| `ValueError`          | 400         | `{"error": "<message>"}`        |
| `ObjectNotFoundError` | 404         | `{"error": "<message>"}`        |
| `InvalidStateError`   | 409         | `{"error": "<message>"}`        |
| `InvalidOperationError` | 422      | `{"error": "<message>"}`        |

When the request runs inside `DomainContextMiddleware`, the body also carries
the request's `correlation_id`, the same value the `X-Correlation-ID` response
header holds.

### Example

```python
--8<-- "guides/fastapi/index/005.py:example-imports"
--8<-- "guides/fastapi/index/005.py:example"
```

---

## Putting it all together

A typical FastAPI application using both utilities:

```python
--8<-- "guides/fastapi/index/006.py:imports"
--8<-- "guides/fastapi/index/006.py:domain"
--8<-- "guides/fastapi/index/006.py:app"
--8<-- "guides/fastapi/index/006.py:endpoint"
```

The endpoints on this page are plain `def` functions. `domain.process()` is a
blocking call, and FastAPI runs a `def` endpoint in its thread pool, so the
call does not hold up the event loop. The domain context that the middleware
pushes reaches the endpoint in that thread.

## Startup and shutdown lifecycle

FastAPI's [lifespan events](https://fastapi.tiangolo.com/advanced/events/)
let you run setup and teardown logic that wraps the entire application
lifetime. This is the recommended place to initialize domains, set up
database schemas, and clean up on shutdown.

### Using the lifespan context manager

```python
--8<-- "guides/fastapi/index/007.py:lifespan-imports"
--8<-- "guides/fastapi/index/007.py:lifespan"
```

### What belongs in startup vs. middleware

| Concern | Where | Why |
|---------|-------|-----|
| `domain.init()` | Startup (lifespan) | Traverses elements, resolves references, connects adapters, once per process |
| `domain.setup_database()` | Startup (lifespan) | Creates tables and outbox, once per deployment |
| Domain context push/pop | Middleware | Each request needs its own context for thread-local state |
| Exception mapping | App setup | Registered once at import time |

### Multi-domain startup

When your application serves multiple bounded contexts, initialize each
domain in the lifespan:

```python
--8<-- "guides/fastapi/index/008.py:multi-domain"
```

### Simple single-domain apps

For simple applications where startup overhead isn't a concern, calling
`domain.init()` at module level remains a valid approach:

```python
--8<-- "guides/fastapi/index/009.py:module-level"
```

This works well for small applications. Use the lifespan approach when you
need database setup, graceful shutdown, or multiple domains.

---

## Other web frameworks

Protean's FastAPI integration provides middleware and exception handlers
as conveniences, but the core mechanism (`domain.domain_context()`) works with any Python web
framework. For Flask, Django, or other WSGI/ASGI frameworks, manually push the
domain context in your request middleware:

```python
--8<-- "guides/fastapi/index/010.py:flask-imports"
--8<-- "guides/fastapi/index/010.py:flask"
```

See [Activate Domain](../compose-a-domain/activate-domain.md) for details
on domain context management.

---

## Next steps

- [Endpoint Tests](./testing-endpoints.md): Test your FastAPI endpoints
  with full domain context
- [Compose a Domain](../compose-a-domain/index.md): How the `Domain`
  object and domain contexts work
- [Commands](../change-state/commands.md): Define commands for state changes
- [Configuration](../../reference/configuration/index.md): Configure databases,
  brokers, and other adapters
