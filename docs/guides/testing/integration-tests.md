# Integration Tests

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Integration tests verify that your application works correctly with real
infrastructure — databases, message brokers, event stores, and caches. They
exercise the same code paths as production, giving you confidence that your
domain logic persists and communicates correctly through real adapters.

Like [application tests](./application-tests.md), we recommend using
**pytest-bdd** for integration tests. The BDD structure works just as well
here — the only difference is the domain is configured with real
infrastructure instead of in-memory adapters.

## Key Facts

- Integration tests use the same feature files and step definitions as
  application tests, but run against real infrastructure.
- Configure your domain with real adapters (PostgreSQL, Redis, etc.)
  via a separate fixture or configuration override.
- Use pytest markers or tags to separate integration tests from fast
  in-memory tests.
- Run in-memory tests during development; run integration tests in CI.

## Configuring for Real Infrastructure

The key difference from application tests is the domain configuration. Override
your database, broker, or event store settings in a dedicated `conftest.py`
and use `DomainFixture` to manage the lifecycle:

```python
# tests/integration/conftest.py
import pytest
from pytest_bdd import given

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["databases"]["default"] = {
        "provider": "protean.adapters.repository.sqlalchemy.SAProvider",
        "database_uri": "postgresql://postgres:postgres@localhost:5432/myapp_test",
    }
    domain.config["brokers"]["default"] = {
        "provider": "protean.adapters.broker.redis.RedisBroker",
        "URI": "redis://localhost:6379/0",
    }
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()    # domain.init() + create schema
    yield fixture
    fixture.teardown()  # drop schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():  # resets all data on exit
        yield


@given("the domain is initialized")
def domain_initialized():
    pass
```

!!!note
    `DomainFixture.setup()` calls `domain.init()` and creates database
    tables for all configured providers. `teardown()` drops them.
    `domain_context()` resets all data (providers, brokers, event store)
    after each test. The same application code and domain elements are
    used — only the infrastructure changes.

## Full-Flow Feature Files

Integration tests exercise complete flows from command to projection,
verifying that every layer works together through real infrastructure.

### Command Through to Projection

```gherkin
# tests/integration/features/order_flow.feature
@integration
Feature: End-to-End Order Flow
    Verify the complete order lifecycle from book creation
    through order fulfillment, including event-driven side effects.

    Background:
        Given the domain is initialized

    Scenario: Full order lifecycle
        Given a book "Dune" is added to the catalog at 15.99
        And the book has 10 copies in stock
        And a customer "Alice" exists
        When "Alice" places an order for 2 copies of "Dune"
        And the order is fulfilled
        Then the order status should be "CONFIRMED"
        And "Dune" should have 8 copies in stock
        And the catalog projection should show 2 copies sold for "Dune"

    Scenario: Order updates customer history across aggregates
        Given a book "1984" is added to the catalog at 11.99
        And the book has 5 copies in stock
        And a customer "Bob" exists
        When "Bob" places an order for 1 copy of "1984"
        Then "Bob" should have 1 order in their history
```

### Persistence Round-Trip

```gherkin
# tests/integration/features/persistence.feature
@integration
Feature: Persistence
    Verify that aggregates survive a round-trip through
    the real database.

    Background:
        Given the domain is initialized

    Scenario: Book survives persistence round-trip
        Given a book "The Great Gatsby" by "F. Scott Fitzgerald" at 12.99
        When the book is persisted and reloaded
        Then the reloaded book should have title "The Great Gatsby"
        And the reloaded book should have price 12.99

    Scenario: Updated aggregate is persisted correctly
        Given a book "Dune" by "Frank Herbert" at 15.99
        And the book is persisted
        When the book price is updated to 19.99
        And the book is persisted and reloaded
        Then the reloaded book should have price 19.99
```

## Step Definitions for Integration Tests

Step definitions are the same as application tests — they import your domain
and use `domain.process()` and `domain.repository_for()`:

```python
# tests/integration/test_order_flow.py
from pytest_bdd import scenarios, given, when, then, parsers

from myapp import domain
from myapp.commands import AddBook, PlaceOrder
from myapp.models import Book, BookCatalog, Customer, Inventory, Order

scenarios("features/order_flow.feature")


@given(
    parsers.parse('a book "{title}" is added to the catalog at {price:f}'),
    target_fixture="book_id",
)
def add_book(title, price):
    return domain.process(
        AddBook(title=title, author="Test Author", price_amount=price)
    )


@given(
    parsers.parse("the book has {quantity:d} copies in stock"),
)
def stock_book(book_id, quantity):
    inventory = Inventory(book_id=book_id, title="", quantity=quantity)
    domain.repository_for(Inventory).add(inventory)


@given(
    parsers.parse('a customer "{name}" exists'),
    target_fixture="customer",
)
def existing_customer(name):
    customer = Customer(name=name)
    domain.repository_for(Customer).add(customer)
    return customer


@when(
    parsers.parse('"{name}" places an order for {qty:d} copies of "{title}"'),
    target_fixture="order",
)
def place_order(customer, book_id, name, qty, title):
    domain.process(
        PlaceOrder(
            customer_id=customer.id,
            items=[{"book_id": book_id, "quantity": qty}],
        )
    )
    orders = domain.repository_for(Order)._dao.query.all()
    return orders.items[0]


@then(parsers.parse('the catalog projection should show {sold:d} copies sold for "{title}"'))
def check_projection(book_id, sold, title):
    catalog = domain.repository_for(BookCatalog).get(book_id)
    assert catalog.copies_sold == sold
```

## Separating Integration Tests

Use Gherkin tags and pytest markers to separate integration tests from fast
in-memory tests:

```gherkin
@integration
Feature: Persistence
    ...
```

Run them selectively:

```shell
# Fast local development — skip integration tests
pytest tests/ -m "not integration"

# CI pipeline — run everything
pytest tests/

# Run only integration tests
pytest tests/ -m integration
```

You can also separate them by directory structure:

```
tests/
├── conftest.py                  # Shared root fixtures
├── unit/                        # Domain model tests (always fast)
│   └── ...
├── bdd/                         # Application tests (in-memory)
│   └── ...
└── integration/                 # Integration tests (real infra)
    ├── conftest.py              # Real adapter configuration
    ├── features/
    │   ├── order_flow.feature
    │   └── persistence.feature
    ├── test_order_flow.py
    └── test_persistence.py
```

## Testing with Different Adapters

To run the same integration tests against different databases or brokers,
use environment variables to switch configuration:

```python
# tests/integration/conftest.py
import os

import pytest

from protean.integrations.pytest import DomainFixture

from myapp import domain


@pytest.fixture(scope="session")
def app_fixture():
    db_provider = os.environ.get("TEST_DB", "memory")

    if db_provider == "postgresql":
        domain.config["databases"]["default"] = {
            "provider": "protean.adapters.repository.sqlalchemy.SAProvider",
            "database_uri": os.environ["DATABASE_URL"],
        }
    elif db_provider == "sqlite":
        domain.config["databases"]["default"] = {
            "provider": "protean.adapters.repository.sqlalchemy.SAProvider",
            "database_uri": "sqlite:///test.db",
        }
    # Default: in-memory (no override needed)

    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()    # domain.init() + create schema
    yield fixture
    fixture.teardown()  # drop schema


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():  # resets all data on exit
        yield
```

Then switch adapters from the command line:

```shell
# Default: in-memory
pytest tests/integration/

# With PostgreSQL
TEST_DB=postgresql DATABASE_URL=postgresql://localhost/myapp_test pytest tests/integration/

# With SQLite
TEST_DB=sqlite pytest tests/integration/
```

This lets the same feature files and step definitions run against any
adapter — the domain logic is identical, only the infrastructure changes.

## Per-Test Data Cleanup

`DomainFixture.domain_context()` automatically resets data in all providers,
brokers, and the event store after each test. If you use the recommended
`_ctx` fixture pattern above, **no additional cleanup fixture is needed**.

## Coverage Reporting

Run your full test suite with coverage to verify you're hitting the 100%
target on business logic:

```shell
# Run all tests with coverage
pytest --cov=myapp --cov-report=html tests/

# Run with a minimum coverage threshold
pytest --cov=myapp --cov-fail-under=100 tests/
```

Exclude setup files from coverage in your `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["myapp"]
omit = ["myapp/__init__.py", "myapp/config.py"]
```
