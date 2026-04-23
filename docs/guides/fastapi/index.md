# FastAPI Integration

Protean provides first-class integration utilities for
[FastAPI](https://fastapi.tiangolo.com/) applications. These live in the
`protean.integrations.fastapi` package and cover two concerns:

1. **Domain context middleware** -- Automatically push the correct Protean
   domain context per HTTP request.
2. **Exception handlers** -- Map Protean domain exceptions to standard HTTP
   error responses.

---

## Domain context middleware

Every Protean operation needs an active domain context. In a FastAPI
application, each HTTP request should run inside the context of the domain
it belongs to. `DomainContextMiddleware` handles this automatically by
matching the request URL path to a `Domain` instance.

### Basic setup

```python
from fastapi import FastAPI
from protean.integrations.fastapi import DomainContextMiddleware

from my_app.identity import identity_domain
from my_app.catalogue import catalogue_domain

app = FastAPI()

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/customers": identity_domain,
        "/products": catalogue_domain,
    },
)
```

With this configuration:

- Requests to `/customers/...` run inside `identity_domain.domain_context()`
- Requests to `/products/...` run inside `catalogue_domain.domain_context()`
- Requests that don't match any prefix (e.g. `/health`) pass through without
  a domain context -- suitable for health checks, docs, and static assets.

### Longest-prefix matching

When multiple prefixes overlap, the longest match wins:

```python
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/api": core_domain,
        "/api/v2": v2_domain,
    },
)
```

A request to `/api/v2/items` matches `/api/v2` (the longer prefix) and uses
`v2_domain`. A request to `/api/v1/items` matches `/api` and uses
`core_domain`.

### Custom resolver

For more advanced routing logic (e.g. tenant-based, header-based, or
database-driven resolution), provide a `resolver` callable instead of a
static map:

```python
from protean.domain import Domain

def resolve_domain(path: str) -> Domain | None:
    """Route /tenant-a/* and /tenant-b/* to separate domains."""
    if path.startswith("/tenant-a"):
        return tenant_a_domain
    if path.startswith("/tenant-b"):
        return tenant_b_domain
    return None  # No domain context for other paths

app.add_middleware(
    DomainContextMiddleware,
    resolver=resolve_domain,
)
```

When a resolver is provided, `route_domain_map` is ignored. Returning `None`
from the resolver means the request proceeds without a domain context.

### Single-domain applications

For applications with only one domain, you can map the root prefix:

```python
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": my_domain},
)
```

### Correlation ID header

The middleware automatically extracts `X-Correlation-ID` (falling back to
`X-Request-ID`) from incoming request headers and makes it available as the
default correlation ID for command processing. The response always includes an
`X-Correlation-ID` header reflecting the ID that was used -- from the request
header, an explicit `domain.process()` parameter, or an auto-generated UUID.

This means no manual header extraction is needed in your endpoints:

```python
@app.post("/orders")
async def place_order(payload: dict):
    # Correlation ID from X-Correlation-ID header is picked up automatically.
    current_domain.process(PlaceOrder(**payload))
    return {"status": "accepted"}
```

For the full story on how correlation IDs propagate through commands, events,
logging, and OTEL spans, see
[Correlation and Causation IDs](../observability/correlation-and-causation.md).

### HTTP wide event logging

`DomainContextMiddleware` also emits one **wide event per HTTP request**
on the `protean.access.http` logger — request envelope, commands
dispatched during the request, `request_id`, and `correlation_id` shared
with any domain-layer wide events. See the dedicated
[HTTP wide events guide](./http-wide-events.md) for configuration,
enrichment, and tail sampling.

---

## Exception handlers

`register_exception_handlers` maps Protean domain exceptions to appropriate
HTTP status codes so that your endpoint code can raise domain exceptions
directly without manual try/except blocks.

### Setup

```python
from fastapi import FastAPI
from protean.integrations.fastapi import register_exception_handlers

app = FastAPI()
register_exception_handlers(app)
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

### Example

```python
from protean.utils.globals import current_domain
from protean.exceptions import ObjectNotFoundError

@app.get("/customers/{customer_id}")
async def get_customer(customer_id: str):
    repo = current_domain.repository_for(Customer)
    customer = repo.get(customer_id)  # Raises ObjectNotFoundError → 404
    return {"id": customer.id, "name": customer.name}
```

---

## Putting it all together

A typical FastAPI application using both utilities:

```python
from fastapi import FastAPI
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)
from protean.utils.globals import current_domain

from my_app.domain import domain

app = FastAPI()

# 1. Middleware: push domain context per request
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)

# 2. Exception handlers: map domain exceptions to HTTP responses
register_exception_handlers(app)


@app.post("/orders")
async def place_order(payload: dict):
    current_domain.process(PlaceOrder(**payload))
    return {"status": "accepted"}
```

## Startup and shutdown lifecycle

FastAPI's [lifespan events](https://fastapi.tiangolo.com/advanced/events/)
let you run setup and teardown logic that wraps the entire application
lifetime. This is the recommended place to initialize domains, set up
database schemas, and clean up on shutdown.

### Using the lifespan context manager

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)

from my_app.domain import domain


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize domain and prepare infrastructure
    domain.init()
    with domain.domain_context():
        domain.setup_database()

    yield

    # Shutdown: release resources
    with domain.domain_context():
        # Any cleanup logic here
        pass


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)
register_exception_handlers(app)
```

### What belongs in startup vs. middleware

| Concern | Where | Why |
|---------|-------|-----|
| `domain.init()` | Startup (lifespan) | Traverses elements, resolves references, connects adapters -- once per process |
| `domain.setup_database()` | Startup (lifespan) | Creates tables and outbox -- once per deployment |
| Domain context push/pop | Middleware | Each request needs its own context for thread-local state |
| Exception mapping | App setup | Registered once at import time |

### Multi-domain startup

When your application serves multiple bounded contexts, initialize each
domain in the lifespan:

```python
from my_app.identity import identity_domain
from my_app.catalogue import catalogue_domain


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize all domains
    for d in [identity_domain, catalogue_domain]:
        d.init()
        with d.domain_context():
            d.setup_database()

    yield

    # Shutdown
    for d in [identity_domain, catalogue_domain]:
        with d.domain_context():
            pass  # Cleanup if needed


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/customers": identity_domain,
        "/products": catalogue_domain,
    },
)
```

### Simple single-domain apps

For simple applications where startup overhead isn't a concern, calling
`domain.init()` at module level remains a valid approach:

```python
from my_app.domain import domain

domain.init()  # Called once at import time

app = FastAPI()
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={"/": domain},
)
```

This works well for small applications. Use the lifespan approach when you
need database setup, graceful shutdown, or multiple domains.

---

## Other web frameworks

Protean's FastAPI integration provides middleware and exception handlers
as conveniences, but the core mechanism -- `domain.domain_context()` -- works
with any Python web framework. For Flask, Django, or other WSGI/ASGI
frameworks, manually push the domain context in your request middleware:

```python
# Flask example
from flask import Flask, g
from my_app.domain import domain

app = Flask(__name__)

@app.before_request
def push_domain_context() -> None:
    ctx = domain.domain_context()
    ctx.push()
    g.domain_ctx = ctx

@app.teardown_request
def pop_domain_context(exc: Exception | None) -> None:
    if hasattr(g, "domain_ctx"):
        g.domain_ctx.pop(exc)
```

See [Activate Domain](../compose-a-domain/activate-domain.md) for details
on domain context management.

---

## Next steps

- [Endpoint Tests](./testing-endpoints.md) -- Test your FastAPI endpoints
  with full domain context
- [Compose a Domain](../compose-a-domain/index.md) -- How the `Domain`
  object and domain contexts work
- [Commands](../change-state/commands.md) -- Define commands for state changes
- [Configuration](../../reference/configuration/index.md) -- Configure databases,
  brokers, and other adapters
