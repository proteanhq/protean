# Endpoint Tests

Protean endpoints are thin adapters. They translate HTTP requests into domain
commands. `domain.process()` then passes each command to its command handler.
An endpoint test checks that the HTTP layer dispatches the correct command and
returns the correct response. The domain runs the business logic. This
separation makes endpoint tests surprisingly straightforward.

## What You're Actually Testing

Endpoint tests check how an endpoint connects HTTP requests to your domain.
They verify:

- **Does the endpoint turn the request into the right command?** It should
  extract the right data from the request and build the correct command.
- **Does the endpoint return the right response?** It should return the right
  status code and body for success and failure cases.
- **Do domain exceptions become the correct HTTP errors?**

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

Take a small bookstore app. A customer places an order for books. An event
handler then takes the ordered books out of stock:

```python
--8<-- "guides/fastapi/testing-endpoints/001.py:domain-imports"
--8<-- "guides/fastapi/testing-endpoints/001.py:domain"
```

In the layout above, this code goes in `myapp/`. Each example below goes in the
file named in its title. The examples leave out the imports of `domain` and the
elements from `myapp`, so each block shows only the new code.

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

The root `conftest.py` uses `DomainFixture` to set up the domain and to clean
up its data after each test. The API-specific `conftest.py` provides the
client. Every test starts with no data left over from previous tests.

!!! tip "Why a separate `tests/api/conftest.py`?"
    With the `TestClient` fixture local to `tests/api/`, pytest does not create
    the FastAPI app for domain model tests and BDD tests that don't need it.
    Through its conftest hierarchy, pytest still makes `_ctx` (domain context)
    available from the root.

## Testing `domain.process()` endpoints

In the most common Protean endpoint pattern, the endpoint accepts a request,
builds a command, and hands it to `domain.process()`:

```python title="myapp/api.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:api-imports"
--8<-- "guides/fastapi/testing-endpoints/001.py:api"
```

### The happy path

```python title="tests/api/test_create_order.py"
--8<-- "guides/fastapi/testing-endpoints/001.py:happy-path"
```

Each test follows three steps:

1. **Seed**: Set up the preconditions using repositories directly.
2. **Act**: Make an HTTP request through the `TestClient`.
3. **Assert**: Check the HTTP response.

The `DomainContextMiddleware` pushes the domain context for the request, so
`current_domain` resolves correctly inside the endpoint. Because
`command_processing` is set to `"sync"`, the command handler runs immediately.
By the time the response returns, all side effects (aggregate creation, events,
projections) have completed.

### Verifying side effects

After the endpoint returns, you may want to verify the state *inside* the
domain. Query the repository directly:

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

A command can raise events that cause cross-aggregate side effects. With sync
processing, all of those side effects complete before the response returns:

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
only makes requests. The middleware activates the domain context for each
request.

## Keeping endpoints thin

The Proteanic way is to keep endpoints as thin adapters. When you write complex
test setups or test business logic through HTTP, move that logic out of the
endpoint and into the domain:

| If your endpoint... | Move it to... |
|---------------------|---------------|
| Validates business rules | Aggregate invariants |
| Orchestrates multiple steps | Command handler |
| Queries and transforms data | Projection + projector |
| Catches and maps exceptions | `register_exception_handlers` |

When endpoints hold no business logic, endpoint tests stay short too. You write
most of your tests as [domain model tests](../testing/domain-model-tests.md)
and [application tests](../testing/application-tests.md). The endpoint tests
are the last check that the HTTP layer passes requests to the domain and
returns its responses.

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
