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

## Next steps

- [Compose a Domain](../compose-a-domain/index.md) -- How the `Domain`
  object and domain contexts work
- [Commands](../change-state/commands.md) -- Define commands for state changes
- [Configuration](../essentials/configuration.md) -- Configure databases,
  brokers, and other adapters
