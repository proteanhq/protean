# Endpoint Tests

Protean endpoints are thin adapters. They translate HTTP into domain commands
and let `domain.process()` handle the rest. Testing them means verifying that
the HTTP layer correctly dispatches commands and returns appropriate responses,
while the domain takes care of business logic. This separation makes endpoint
tests surprisingly straightforward.

## What You're Actually Testing

Endpoint tests sit at the boundary between HTTP and your domain. They verify:

- **Request → Command translation**: Does the endpoint extract the right
  data from the request and build the correct command?
- **Response shaping**: Does the endpoint return the right status code
  and body for success and failure cases?
- **Error mapping**: Do domain exceptions become the correct HTTP errors?

They do *not* test business logic, that belongs in [domain model
tests](../testing/domain-model-tests.md) and [application
tests](../testing/application-tests.md).

## Setup

### Install dependencies

```shell
pip install fastapi httpx
```

Or with uv:

```shell
uv add fastapi httpx
```

!!! note
    FastAPI's `TestClient` is powered by
    [httpx](https://www.python-httpx.org/) internally. You need `httpx`
    installed for `TestClient` to work.

### Project layout

A typical Protean + FastAPI project separates the domain from the web layer:

```
myapp/
├── domain.py              # Domain instance + element discovery
├── models.py              # Aggregates, entities, value objects
├── commands.py            # Commands
├── handlers.py            # Command handlers, event handlers
├── api.py                 # FastAPI app + endpoints
└── domain.toml            # Configuration
tests/
├── conftest.py            # Domain fixture + FastAPI client
├── unit/                  # Domain model tests
├── bdd/                   # Application tests (pytest-bdd)
└── api/                   # Endpoint tests ← this guide
    ├── conftest.py        # API-specific fixtures
    ├── test_create_order.py
    └── test_get_customer.py
```

### The example app

Take a small bookstore app. A customer places an order for books, and an event
handler takes the ordered books out of stock:

```python
--8<-- "guides/fastapi/testing-endpoints/001.py:domain-imports"
--8<-- "guides/fastapi/testing-endpoints/001.py:domain"
```

In the layout above, this code lives in `myapp/`, and each example below goes
in the file named in its title. The examples leave out the imports of `domain`
and the elements from `myapp`, so each block shows only the new code.

### The `conftest.py` recipe

Endpoint tests need two things: a domain that processes commands synchronously,
and a FastAPI `TestClient` wired to that domain.

```python title="tests/conftest.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:pytest-import"
--8<-- "guides/fastapi/testing-endpoints/001.py:fixture-import"
--8<-- "guides/fastapi/testing-endpoints/001.py:conftest"
```

```python title="tests/api/conftest.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:pytest-import"
--8<-- "guides/fastapi/testing-endpoints/001.py:client-import"
--8<-- "guides/fastapi/testing-endpoints/001.py:client"
```

That's it. The root `conftest.py` handles domain lifecycle and per-test cleanup
(via `DomainFixture`). The API-specific `conftest.py` provides the client.
Every test starts with a clean slate, no leftover data from previous tests.

!!! tip "Why a separate `tests/api/conftest.py`?"
    Keeping the `TestClient` fixture local to `tests/api/` avoids creating
    the FastAPI app for domain model tests and BDD tests that don't need it.
    pytest's conftest hierarchy means `_ctx` (domain context) is still
    available from the root.

## Testing `domain.process()` endpoints

The most common Protean endpoint pattern accepts a request, builds a command,
and hands it to `domain.process()`:

```python title="myapp/api.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:api-imports"
--8<-- "guides/fastapi/testing-endpoints/001.py:api"
```

### The happy path

```python title="tests/api/test_create_order.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:happy-path"
```

Notice the pattern:

1. **Seed**: Set up the preconditions using repositories directly.
2. **Act**: Make an HTTP request through the `TestClient`.
3. **Assert**: Check the HTTP response.

The `DomainContextMiddleware` pushes the domain context for the request,
so `current_domain` resolves correctly inside the endpoint. And because
`command_processing` is set to `"sync"`, the command handler runs
immediately, by the time the response returns, all side effects (aggregate
creation, events, projections) have completed.

### Verifying side effects

Sometimes you want to verify what happened *inside* the domain after the
endpoint returns. Query the repository directly:

```python
--8<-- "guides/fastapi/testing-endpoints/001.py:side-effects"
```

### Testing error responses

With `register_exception_handlers` in place, domain exceptions become
proper HTTP errors automatically:

```python
--8<-- "guides/fastapi/testing-endpoints/001.py:errors"
```

The endpoint code doesn't need try/except. It raises domain exceptions
naturally, and the exception handlers translate them into HTTP responses. This
keeps endpoints thin and tests focused on behavior.

## Testing query endpoints

Query endpoints read from repositories or projections. They don't process
commands:

```python title="myapp/api.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:query-endpoint"
```

```python title="tests/api/test_get_customer.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:query-tests"
```

## Testing event-driven side effects through endpoints

When a command triggers events that cause cross-aggregate side effects,
sync processing ensures everything completes before the response returns:

```python
--8<-- "guides/fastapi/testing-endpoints/001.py:event-side-effects"
```

With `event_processing = "sync"`, event handlers and projectors fire
synchronously within the same request. This gives you full end-to-end
confidence without needing to poll or wait.

## Fixture patterns for endpoint tests

### Seed data fixture

When multiple tests need the same preconditions:

```python title="tests/api/conftest.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:pytest-import"
--8<-- "guides/fastapi/testing-endpoints/001.py:client-import"
--8<-- "guides/fastapi/testing-endpoints/001.py:client"
--8<-- "guides/fastapi/testing-endpoints/001.py:alice"
```

```python title="tests/api/test_create_order.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:seed-fixture-test"
```

### Authenticated request fixture

For endpoints behind authentication:

```python
--8<-- "guides/fastapi/testing-endpoints/001.py:auth-client"
```

### Response assertion helpers

For repeated response shape checks:

```python
--8<-- "guides/fastapi/testing-endpoints/001.py:assert-helper"
```

## Multi-domain applications

When your application has multiple bounded contexts, the middleware maps
URL prefixes to domains. Tests create separate clients or use the same
client with different URL paths:

```python title="myapp/api.py"
--8<-- "guides/fastapi/testing-endpoints/002.py:api-imports"
--8<-- "guides/fastapi/testing-endpoints/002.py:api"
```

```python title="tests/api/conftest.py"
--8<-- "guides/fastapi/testing-endpoints/002.py:conftest-imports"
--8<-- "guides/fastapi/testing-endpoints/002.py:conftest"
```

Each request path activates the correct domain context automatically. The test
makes requests, the middleware handles the rest.

## Keeping endpoints thin

The Proteanic way is to keep endpoints as thin adapters. If you find
yourself writing complex test setups or testing business logic through
HTTP, that's a signal to push the logic down:

| If your endpoint... | Move it to... |
|---------------------|---------------|
| Validates business rules | Aggregate invariants |
| Orchestrates multiple steps | Command handler |
| Queries and transforms data | Projection + projector |
| Catches and maps exceptions | `register_exception_handlers` |

When endpoints are thin, endpoint tests become thin too. Most of your testing
energy goes into [domain model tests](../testing/domain-model-tests.md) and
[application tests](../testing/application-tests.md). The endpoint tests are
just the final sanity check that HTTP wiring works.

## Checklist

Before shipping endpoint tests, verify:

- [ ] `command_processing` and `event_processing` are set to `"sync"`
  in your test configuration
- [ ] `DomainContextMiddleware` is configured on the app so `current_domain`
  resolves correctly
- [ ] `register_exception_handlers` is called so domain exceptions map
  to HTTP status codes
- [ ] Each test seeds its own data, no shared mutable state between tests
- [ ] `DomainFixture.domain_context()` resets all data after each test
  (via the `_ctx` autouse fixture)

## Next steps

- [FastAPI Integration](./index.md): Middleware and exception handler
  reference
- [Fixtures and Patterns](../testing/fixtures-and-patterns.md): Reusable
  test recipes for Protean projects
- [Application Tests](../testing/application-tests.md): BDD-style tests
  for command and event handler logic
