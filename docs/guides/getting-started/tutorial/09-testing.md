# Chapter 9: Testing Your Domain

In this chapter we will set up pytest for Bookshelf and write tests that
verify our business logic — commands, events, invariants, and projections.

!!! tip "Focus on business logic"
    Protean handles field validation, immutability, and wiring automatically.
    Your tests should focus on the behavior *you* wrote — invariants, state
    transitions, command flows, and event reactions. For a deeper discussion,
    see [Testing](../../testing/index.md).

## Setting Up Tests

Protean ships with a pytest plugin and `DomainFixture` that handles
initialization, context management, and cleanup. Create a `conftest.py`:

```python
import pytest

from protean.integrations.pytest import DomainFixture
from protean.utils.globals import current_domain

from bookshelf import domain


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
domain elements, and creates database schema if needed. The `_ctx`
fixture activates the domain context for each test and resets all data
on exit. Inside your tests, use `current_domain` to access the active
domain.

## Testing Aggregates and Invariants

Test the business rules *you* wrote — invariants, state guards, and
meaningful state transitions:

```python
from bookshelf.models import Book, Order, OrderItem, Money

def test_order_must_have_items():
    with pytest.raises(ValidationError) as exc:
        Order(customer_name="Alice")
    assert "at least one item" in str(exc.value.messages)

def test_cannot_modify_shipped_order():
    order = Order(
        customer_name="Alice",
        items=[
            OrderItem(
                book_title="Gatsby", quantity=1, price=Money(amount=12.99)
            )
        ],
    )
    order.ship()

    with pytest.raises(ValidationError) as exc:
        order.add_item("Another Book", 1, Money(amount=9.99))
    assert "shipped" in str(exc.value.messages)
```

### Testing Value Objects

Value object tests should focus on domain behavior — equality semantics
and any custom logic:

```python
from bookshelf.models import Money

def test_money_equality():
    m1 = Money(amount=12.99, currency="USD")
    m2 = Money(amount=12.99, currency="USD")
    m3 = Money(amount=14.99, currency="USD")

    assert m1 == m2
    assert m1 != m3
```

## Testing Commands and Handlers

Test the full command processing flow. The `_ctx` fixture ensures
`current_domain` is available:

```python
from bookshelf.commands import AddBook
from bookshelf.models import Book, Inventory

def test_add_book_command():
    book_id = current_domain.process(
        AddBook(
            title="The Great Gatsby",
            author="F. Scott Fitzgerald",
            price_amount=12.99,
        ),
        asynchronous=False,
    )

    book = current_domain.repository_for(Book).get(book_id)
    assert book.title == "The Great Gatsby"
    assert book.price.amount == 12.99

def test_add_book_raises_event():
    current_domain.process(
        AddBook(
            title="Dune",
            author="Frank Herbert",
            price_amount=15.99,
        ),
        asynchronous=False,
    )

    # With sync processing, the event handler runs immediately
    inventories = current_domain.repository_for(Inventory)._dao.query.all()
    assert inventories.total == 1
```

## Testing Events and Event Handlers

Verify that events trigger the expected reactions:

```python
from bookshelf.models import Book, Inventory, Money

def test_book_added_creates_inventory():
    """When a book is added, an inventory record should be created."""
    book = Book(
        title="1984",
        author="George Orwell",
        price=Money(amount=11.99),
    )
    book.add_to_catalog()
    current_domain.repository_for(Book).add(book)

    inventories = current_domain.repository_for(Inventory)._dao.query.all()
    assert inventories.total == 1
    assert inventories.items[0].title == "1984"
```

## Testing Projections

Verify that projectors maintain projections correctly:

```python
from bookshelf.models import Book, BookCatalog

def test_book_catalog_projection():
    """Adding a book should create a catalog entry."""
    book = Book.add_to_catalog(
        title="Dune",
        author="Frank Herbert",
        price_amount=15.99,
    )
    current_domain.repository_for(Book).add(book)

    catalog = current_domain.repository_for(BookCatalog).get(book.id)
    assert catalog.title == "Dune"
    assert catalog.price == 15.99
```

## Integration Testing

Test complete flows from command to final state:

```python
from bookshelf.commands import AddBook
from bookshelf.models import Order, OrderItem, Money

def test_full_order_flow():
    """End-to-end: add book -> place order -> verify."""
    book_id = current_domain.process(
        AddBook(title="Dune", author="Frank Herbert", price_amount=15.99),
        asynchronous=False,
    )

    order = Order(
        customer_name="Alice",
        items=[
            OrderItem(
                book_title="Dune", quantity=2, price=Money(amount=15.99)
            )
        ],
    )
    current_domain.repository_for(Order).add(order)

    order.confirm()
    current_domain.repository_for(Order).add(order)

    saved = current_domain.repository_for(Order).get(order.id)
    assert saved.status == "CONFIRMED"
```

## Running Tests

Run the tests:

```shell
$ pytest -v
```

All tests use in-memory adapters by default — no Docker, no database
setup, no manual cleanup. For testing against real infrastructure, see
the [Testing guide](../../testing/index.md) and the
[Dual-Mode Testing](../../../patterns/dual-mode-testing.md) pattern.

## What We Built

- **Test fixtures** with `DomainFixture` for automatic setup and teardown.
- **Invariant tests** for business rules and state guards.
- **Command flow tests** from dispatch to persisted state.
- **Event handler tests** verifying automatic side effects.
- **Projection tests** confirming projector output.
- An **integration test** covering a complete end-to-end flow.

Congratulations — we have built a fully tested bookstore application!
In the next chapter, we will see where to go from here.

## Next

[Chapter 10: What Comes Next →](10-whats-next.md)
