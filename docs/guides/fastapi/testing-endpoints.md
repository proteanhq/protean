# Endpoint Tests

Protean endpoints are thin adapters — they translate HTTP into domain commands
and let `domain.process()` handle the rest. Testing them means verifying that
the HTTP layer correctly dispatches commands and returns appropriate responses,
while the domain takes care of business logic. This separation makes endpoint
tests surprisingly straightforward.

## What You're Actually Testing

Endpoint tests sit at the boundary between HTTP and your domain. They verify:

- **Request → Command translation** — Does the endpoint extract the right
  data from the request and build the correct command?
- **Response shaping** — Does the endpoint return the right status code
  and body for success and failure cases?
- **Error mapping** — Do domain exceptions become the correct HTTP errors?

They do *not* test business logic — that belongs in
[domain model tests](../testing/domain-model-tests.md) and
[application tests](../testing/application-tests.md).

## Setup

### Install dependencies

```shell
pip install fastapi httpx
```

Or with Poetry:

```shell
poetry add fastapi httpx
```

!!! note
    FastAPI's `TestClient` is powered by
    [httpx](https://www.python-httpx.org/) under the hood. You need `httpx`
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

### The `conftest.py` recipe

Endpoint tests need two things: a domain that processes commands synchronously,
and a FastAPI `TestClient` wired to that domain.

```python
# tests/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp.domain import domain


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield
```

```python
# tests/api/conftest.py
import pytest

from fastapi.testclient import TestClient

from myapp.api import app


@pytest.fixture
def client():
    return TestClient(app)
```

That's it. The root `conftest.py` handles domain lifecycle and per-test
cleanup (via `DomainFixture`). The API-specific `conftest.py` just provides
the client. Every test starts with a clean slate — no leftover data from
previous tests.

!!! tip "Why a separate `tests/api/conftest.py`?"
    Keeping the `TestClient` fixture local to `tests/api/` avoids creating
    the FastAPI app for domain model tests and BDD tests that don't need it.
    pytest's conftest hierarchy means `_ctx` (domain context) is still
    available from the root.

## Testing `domain.process()` endpoints

The most common Protean endpoint pattern accepts a request, builds a command,
and hands it to `domain.process()`:

```python
# myapp/api.py
from fastapi import FastAPI
from pydantic import BaseModel

from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)
from protean.utils.globals import current_domain

from myapp.commands import PlaceOrder, OrderItemVO
from myapp.domain import domain

app = FastAPI()
app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})
register_exception_handlers(app)


class PlaceOrderRequest(BaseModel):
    customer_id: str
    items: list[dict]


@app.post("/orders", status_code=201)
def place_order(payload: PlaceOrderRequest):
    order_id = current_domain.process(
        PlaceOrder(
            customer_id=payload.customer_id,
            items=[OrderItemVO(**item) for item in payload.items],
        )
    )
    return {"order_id": order_id}
```

### The happy path

```python
# tests/api/test_create_order.py
from myapp.models import Customer, Order


def test_place_order_returns_201(client):
    # Seed the customer that the order references
    from myapp.domain import domain

    customer = Customer(name="Alice")
    domain.repository_for(Customer).add(customer)

    response = client.post("/orders", json={
        "customer_id": customer.id,
        "items": [{"book_id": "book-1", "quantity": 2}],
    })

    assert response.status_code == 201
    assert "order_id" in response.json()
```

Notice the pattern:

1. **Seed** — Set up the preconditions using repositories directly.
2. **Act** — Make an HTTP request through the `TestClient`.
3. **Assert** — Check the HTTP response.

The `DomainContextMiddleware` pushes the domain context for the request,
so `current_domain` resolves correctly inside the endpoint. And because
`command_processing` is set to `"sync"`, the command handler runs
immediately — by the time the response returns, all side effects
(aggregate creation, events, projections) have completed.

### Verifying side effects

Sometimes you want to verify what happened *inside* the domain after the
endpoint returns. Query the repository directly:

```python
def test_place_order_creates_order(client):
    from myapp.domain import domain

    customer = Customer(name="Bob")
    domain.repository_for(Customer).add(customer)

    response = client.post("/orders", json={
        "customer_id": customer.id,
        "items": [{"book_id": "book-1", "quantity": 3}],
    })

    order_id = response.json()["order_id"]
    order = domain.repository_for(Order).get(order_id)
    assert order.customer_id == customer.id
    assert order.status == "PENDING"
```

### Testing error responses

With `register_exception_handlers` in place, domain exceptions become
proper HTTP errors automatically:

```python
def test_place_order_for_nonexistent_customer_returns_404(client):
    response = client.post("/orders", json={
        "customer_id": "nonexistent",
        "items": [{"book_id": "book-1", "quantity": 1}],
    })

    assert response.status_code == 404
    assert "error" in response.json()


def test_place_order_with_invalid_data_returns_400(client):
    response = client.post("/orders", json={
        "customer_id": "",
        "items": [],
    })

    assert response.status_code == 400
```

The endpoint code doesn't need try/except — it raises domain exceptions
naturally, and the exception handlers translate them into HTTP responses.
This keeps endpoints thin and tests focused on behavior.

## Testing query endpoints

Query endpoints read from repositories or projections. They don't process
commands:

```python
# myapp/api.py
from myapp.models import Customer

@app.get("/customers/{customer_id}")
def get_customer(customer_id: str):
    customer = current_domain.repository_for(Customer).get(customer_id)
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
    }
```

```python
# tests/api/test_get_customer.py
from myapp.domain import domain
from myapp.models import Customer


def test_get_customer_returns_200(client):
    customer = Customer(name="Alice", email="alice@example.com")
    domain.repository_for(Customer).add(customer)

    response = client.get(f"/customers/{customer.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Alice"
    assert data["email"] == "alice@example.com"


def test_get_nonexistent_customer_returns_404(client):
    response = client.get("/customers/does-not-exist")

    assert response.status_code == 404
```

## Testing event-driven side effects through endpoints

When a command triggers events that cause cross-aggregate side effects,
sync processing ensures everything completes before the response returns:

```python
def test_placing_order_updates_inventory(client):
    from myapp.domain import domain
    from myapp.models import Customer, Inventory

    customer = Customer(name="Alice")
    domain.repository_for(Customer).add(customer)

    inventory = Inventory(book_id="book-1", quantity=10)
    domain.repository_for(Inventory).add(inventory)

    client.post("/orders", json={
        "customer_id": customer.id,
        "items": [{"book_id": "book-1", "quantity": 3}],
    })

    # The OrderPlaced event handler has already run (sync processing)
    updated = domain.repository_for(Inventory).get(inventory.id)
    assert updated.quantity == 7
```

With `event_processing = "sync"`, event handlers and projectors fire
synchronously within the same request. This gives you full end-to-end
confidence without needing to poll or wait.

## Fixture patterns for endpoint tests

### Seed data fixture

When multiple tests need the same preconditions:

```python
# tests/api/conftest.py
import pytest

from fastapi.testclient import TestClient

from myapp.api import app
from myapp.domain import domain
from myapp.models import Customer


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def alice():
    """A pre-existing customer for order tests."""
    customer = Customer(name="Alice", email="alice@example.com")
    domain.repository_for(Customer).add(customer)
    return customer
```

```python
# tests/api/test_create_order.py
def test_place_order(client, alice):
    response = client.post("/orders", json={
        "customer_id": alice.id,
        "items": [{"book_id": "book-1", "quantity": 1}],
    })
    assert response.status_code == 201
```

### Authenticated request fixture

For endpoints behind authentication:

```python
@pytest.fixture
def auth_client(client):
    """Client with a valid auth token."""
    client.headers["Authorization"] = "Bearer test-token-for-alice"
    return client
```

### Response assertion helpers

For repeated response shape checks:

```python
def assert_error_response(response, status_code, message_fragment=None):
    """Assert that the response is an error with the expected status."""
    assert response.status_code == status_code
    data = response.json()
    assert "error" in data
    if message_fragment:
        error_text = str(data["error"])
        assert message_fragment in error_text
```

## Multi-domain applications

When your application has multiple bounded contexts, the middleware maps
URL prefixes to domains. Tests create separate clients or use the same
client with different URL paths:

```python
# myapp/api.py
from myapp.identity import identity_domain
from myapp.ordering import ordering_domain

app = FastAPI()
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/customers": identity_domain,
        "/orders": ordering_domain,
    },
)
```

```python
# tests/api/conftest.py
import pytest

from protean.integrations.pytest import DomainFixture

from myapp.identity import identity_domain
from myapp.ordering import ordering_domain


@pytest.fixture(scope="session")
def identity_fixture():
    identity_domain.config["command_processing"] = "sync"
    identity_domain.config["event_processing"] = "sync"
    fixture = DomainFixture(identity_domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(scope="session")
def ordering_fixture():
    ordering_domain.config["command_processing"] = "sync"
    ordering_domain.config["event_processing"] = "sync"
    fixture = DomainFixture(ordering_domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(identity_fixture, ordering_fixture):
    with identity_fixture.domain_context():
        with ordering_fixture.domain_context():
            yield
```

Each request path activates the correct domain context automatically.
The test just makes requests — the middleware handles the rest.

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

When endpoints are thin, endpoint tests become thin too. Most of your
testing energy goes into [domain model tests](../testing/domain-model-tests.md)
and [application tests](../testing/application-tests.md) — the endpoint
tests are just the final sanity check that HTTP wiring works.

## Checklist

Before shipping endpoint tests, verify:

- [ ] `command_processing` and `event_processing` are set to `"sync"`
  in your test configuration
- [ ] `DomainContextMiddleware` is configured on the app so `current_domain`
  resolves correctly
- [ ] `register_exception_handlers` is called so domain exceptions map
  to HTTP status codes
- [ ] Each test seeds its own data — no shared mutable state between tests
- [ ] `DomainFixture.domain_context()` resets all data after each test
  (via the `_ctx` autouse fixture)

## Next steps

- [FastAPI Integration](./index.md) — Middleware and exception handler
  reference
- [Fixtures and Patterns](../testing/fixtures-and-patterns.md) — Reusable
  test recipes for Protean projects
- [Application Tests](../testing/application-tests.md) — BDD-style tests
  for command and event handler logic
