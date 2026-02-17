# Chapter 15: Testing Your Domain

A rich domain model is only valuable if you can trust it. In this final
chapter, we cover testing strategies for every layer of your Bookshelf
application.

## Testing Philosophy

Protean's testing approach follows a few principles:

1. **Test domain logic, not framework mechanics** — you don't need to
   test that `String(required=True)` works. Test your business rules.
2. **Avoid mocks** — use real (in-memory) adapters instead. They behave
   like production adapters but need no infrastructure.
3. **Test the whole flow** — commands → events → projections, not just
   individual units.

## Setting Up Tests

Protean ships with a pytest plugin and `DomainFixture` that make testing
straightforward. No Docker, no database setup, no manual cleanup:

```python
import pytest
from protean.integrations.pytest import DomainFixture

from myapp import domain


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

`DomainFixture.setup()` calls `domain.init()` to discover and wire all
your decorated domain elements, and creates database schema if needed.
The `_ctx` fixture activates the domain context for each test and
automatically resets all data (providers, brokers, event store) on exit.

## Testing Aggregates

Test that your aggregates enforce business rules:

```python
def test_create_book(domain):
    book = Book(
        title="The Great Gatsby",
        author="F. Scott Fitzgerald",
        price=Money(amount=12.99),
    )
    assert book.title == "The Great Gatsby"
    assert book.price.amount == 12.99

def test_book_requires_title(domain):
    with pytest.raises(ValidationError) as exc:
        Book(author="Unknown")
    assert "title" in exc.value.messages

def test_order_must_have_items(domain):
    with pytest.raises(ValidationError) as exc:
        Order(customer_name="Alice")
    assert "at least one item" in str(exc.value.messages)
```

### Testing Invariants

```python
def test_cannot_modify_shipped_order(domain):
    order = Order(
        customer_name="Alice",
        items=[OrderItem(book_title="Gatsby", quantity=1, ...)],
    )
    order.ship()

    with pytest.raises(ValidationError) as exc:
        order.add_item("Another Book", 1, Money(amount=9.99))
    assert "shipped" in str(exc.value.messages)
```

### Testing Value Objects

```python
def test_money_equality():
    m1 = Money(amount=12.99, currency="USD")
    m2 = Money(amount=12.99, currency="USD")
    m3 = Money(amount=14.99, currency="USD")

    assert m1 == m2
    assert m1 != m3

def test_money_is_immutable():
    m = Money(amount=12.99)
    with pytest.raises(InvalidOperationError):
        m.amount = 14.99
```

## Testing Commands and Handlers

Test the full command processing flow:

```python
def test_add_book_command(domain):
    book_id = domain.process(
        AddBook(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            price_amount=12.99,
        )
    )

    # Verify the book was persisted
    book = domain.repository_for(Book).get(book_id)
    assert book.title == "The Great Gatsby"
    assert book.price.amount == 12.99

def test_add_book_raises_event(domain):
    book_id = domain.process(
        AddBook(
            title="Dune",
            author="Frank Herbert",
            price_amount=15.99,
        )
    )

    # With sync processing, events are dispatched immediately
    # Verify side effects (e.g., inventory created by handler)
    inventories = domain.repository_for(Inventory)._dao.query.all()
    assert inventories.total == 1
```

## Testing Events and Event Handlers

Verify that events trigger the expected reactions:

```python
def test_book_added_creates_inventory(domain):
    """When a book is added, an inventory record should be created."""
    book = Book(
        title="1984",
        author="George Orwell",
        price=Money(amount=11.99),
    )
    book.add_to_catalog()
    domain.repository_for(Book).add(book)

    # The BookEventHandler should have created inventory
    inventories = domain.repository_for(Inventory)._dao.query.all()
    assert inventories.total == 1
    assert inventories.items[0].title == "1984"

def test_order_confirmed_notification(domain, capsys):
    """When an order is confirmed, a notification should be printed."""
    order = Order(
        customer_name="Alice",
        items=[OrderItem(book_title="1984", quantity=1, ...)],
    )
    domain.repository_for(Order).add(order)

    order.confirm()
    domain.repository_for(Order).add(order)

    captured = capsys.readouterr()
    assert "confirmed" in captured.out.lower()
```

## Testing Projections

Verify that projectors maintain projections correctly:

```python
def test_book_catalog_projection(domain):
    """Adding a book should create a catalog entry."""
    book = Book.add_to_catalog(
        title="Dune",
        author="Frank Herbert",
        price_amount=15.99,
    )
    domain.repository_for(Book).add(book)

    # Projector should have created a catalog entry
    catalog = domain.repository_for(BookCatalog).get(book.id)
    assert catalog.title == "Dune"
    assert catalog.price == 15.99

def test_price_update_reflects_in_catalog(domain):
    """Updating a book's price should update the catalog."""
    book = Book.add_to_catalog(
        title="Dune",
        author="Frank Herbert",
        price_amount=15.99,
    )
    domain.repository_for(Book).add(book)

    book.update_price(19.99)
    domain.repository_for(Book).add(book)

    catalog = domain.repository_for(BookCatalog).get(book.id)
    assert catalog.price == 19.99
```

## Testing with Different Adapters

Protean's test runner supports testing against different infrastructure:

```shell
# Default: in-memory adapters
protean test

# Test with PostgreSQL
protean test --postgresql

# Test with Redis broker
protean test --redis

# Test all database implementations
protean test -c DATABASE

# Test all broker implementations
protean test -c BROKER

# Full test suite with coverage
protean test -c FULL
```

### pytest Markers

Use markers to tag tests that require specific infrastructure:

```python
import pytest

@pytest.mark.database
def test_book_persistence_with_real_db(domain):
    """Test that books persist correctly with a real database."""
    ...

@pytest.mark.broker
def test_events_published_to_broker(domain):
    """Test that events reach the message broker."""
    ...
```

These markers let you skip infrastructure-dependent tests in local
development and run them in CI with the appropriate services.

## Integration Testing

Test complete flows from command to projection:

```python
def test_full_order_flow(domain):
    """End-to-end: add book → place order → fulfill → verify."""
    # Add a book
    book_id = domain.process(
        AddBook(title="Dune", author="Frank Herbert", price_amount=15.99)
    )

    # Create and fulfill an order
    order = Order(
        customer_name="Alice",
        payment_id="pay-123",
        items=[OrderItem(book_title="Dune", quantity=2, ...)],
    )
    domain.repository_for(Order).add(order)

    inventory = Inventory(book_id=book_id, title="Dune", quantity=10)
    domain.repository_for(Inventory).add(inventory)

    service = OrderFulfillmentService(order, [inventory])
    service.fulfill()

    # Verify the complete state
    assert order.status == "CONFIRMED"
    assert inventory.quantity == 8  # 10 - 2
```

## Summary

In this chapter you learned:

- **Test domain logic**, not framework mechanics — use in-memory adapters
  for fast, isolated tests.
- Test **aggregates** for business rules and invariant enforcement.
- Test **commands** end-to-end: dispatch → handler → verify state.
- Test **events** by verifying handler side effects (e.g., inventory
  creation, notifications).
- Test **projections** by verifying projector output after events.
- Use **`protean test`** with flags to test against different adapters.
- Use **pytest markers** to tag infrastructure-dependent tests.

## What's Next?

Congratulations! You have built a complete online bookstore with Protean,
covering every major domain element:

| Part | What You Learned |
|------|-----------------|
| **I. Getting Started** | Aggregates, fields, identity, repositories |
| **II. Domain Model** | Value objects, entities, associations, invariants |
| **III. Commands & Events** | Commands, handlers, domain events, event handlers |
| **IV. Services & Reads** | Application services, domain services, projections |
| **V. Infrastructure** | Configuration, databases, brokers, event sourcing |
| **VI. Quality** | Testing strategies across every layer |

### Continue Learning

- **[Guides](../../compose-a-domain/index.md)** — deep dives into each
  concept
- **[Core Concepts](../../../core-concepts/ddd.md)** — DDD, CQRS, and
  Event Sourcing theory
- **[Adapters](../../../adapters/index.md)** — database, broker, cache,
  and event store adapters
- **[Server](../../server/index.md)** — async processing engine in depth
- **[CLI](../../cli/index.md)** — all command-line tools
