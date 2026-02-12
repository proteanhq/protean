# Domain Model Tests

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Domain model tests are **unit tests** that validate your aggregates, entities,
value objects, invariants, and domain services. They are the foundation of your
test suite — fast, isolated, and focused on business rules.

## Key Facts

- Domain model tests require **no infrastructure** — they run entirely
  in-memory.
- They test **your** business logic: state transitions, invariant enforcement,
  event raising, and domain service orchestration.
- They are the fastest tests in your suite and should form the bulk of your
  coverage.
- Every business rule encoded in your domain model should have a corresponding
  test.

!!!note "Don't Test What Protean Guarantees"
    Protean already guarantees that fields work correctly — `required=True`
    raises validation errors, `max_length` is enforced, `default` values are
    applied, value objects are immutable and compared by value, and events are
    dispatched in order. You do not need to write tests for these behaviors.
    Focus your tests on logic **you** wrote: custom methods, state transitions,
    invariants, and domain rules.

## Test Setup

Domain model tests import your application's domain and initialize it with
in-memory adapters (the default). Override processing to `"sync"` so that
events and commands are handled immediately within tests:

```python
# tests/conftest.py
import pytest

from myapp import domain


@pytest.fixture(autouse=True)
def setup_domain():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"
    domain.init()

    with domain.domain_context():
        yield
```

Since your domain elements are already decorated and registered in your
application code, you do not need to register them again in tests —
`domain.init()` discovers and wires everything automatically.

!!!note
    You do not need Docker, databases, or message brokers for domain model
    tests. Protean's in-memory adapters are used by default.

## Testing Aggregates

Aggregates are the core of your domain model. Test that your custom methods
correctly transition state and raise events.

### State Transitions

Test that aggregate methods correctly mutate state. These are methods **you**
wrote — your business logic:

```python
from myapp.models import Book


def test_publish_changes_status():
    book = Book(
        title="Dune",
        author="Frank Herbert",
        body="A lengthy description...",
    )
    book.publish()

    assert book.status == "PUBLISHED"
```

### Event Raising

Verify that your aggregate methods raise the expected domain events:

```python
from myapp.models import Book
from myapp.events import BookPublished


def test_publish_raises_event():
    book = Book(
        title="Dune",
        author="Frank Herbert",
        body="A lengthy description...",
    )
    book.publish()

    assert len(book._events) == 1
    assert isinstance(book._events[0], BookPublished)
    assert book._events[0].book_id == book.id
```

## Testing Entities

Entities live within aggregates and have their own identity. Test the business
logic in entity methods, especially when they affect the parent aggregate's
state:

```python
from myapp.models import Order, OrderItem


def test_cancel_item_recalculates_order_total():
    order = Order(
        customer_name="Alice",
        total_amount=30.0,
        items=[
            OrderItem(product_id="prod-1", quantity=2, price=10.0, subtotal=20.0),
            OrderItem(product_id="prod-2", quantity=1, price=10.0, subtotal=10.0),
        ],
    )
    order.cancel_item("prod-2")

    assert len(order.items) == 1
    assert order.total_amount == 20.0
```

## Testing Value Objects

Protean guarantees that value objects are immutable and compared by value — you
do not need to test these properties. Instead, test any **custom logic** you
define on your value objects:

```python
from myapp.models import Money


def test_money_addition():
    m1 = Money(amount=12.99, currency="USD")
    m2 = Money(amount=7.01, currency="USD")

    total = m1.add(m2)

    assert total.amount == 20.00
    assert total.currency == "USD"


def test_money_rejects_different_currencies():
    usd = Money(amount=10.0, currency="USD")
    eur = Money(amount=10.0, currency="EUR")

    with pytest.raises(ValidationError) as exc:
        usd.add(eur)
    assert "Cannot add different currencies" in str(exc.value.messages)
```

## Testing Invariants

Invariants are **your** business rules — they represent domain constraints
that you define. Protean guarantees that invariants are *enforced* (triggered
on initialization and mutation), but you should test that **your invariant
logic is correct** and catches the violations you intend.

### Testing That Invalid State Is Rejected

```python
from myapp.models import Order, OrderItem


def test_order_total_must_match_items():
    with pytest.raises(ValidationError) as exc:
        Order(
            customer_id="1",
            total_amount=100.0,  # Does not match items
            items=[
                OrderItem(product_id="1", quantity=2, price=10.0, subtotal=20.0),
            ],
        )
    assert "Total should be sum of item prices" in str(exc.value.messages)
```

### Testing That Valid State Is Accepted

Don't just test the negative case — verify that correctly constructed
aggregates pass your invariant:

```python
def test_order_with_matching_total_is_valid():
    order = Order(
        customer_id="1",
        total_amount=20.0,
        items=[
            OrderItem(product_id="1", quantity=2, price=10.0, subtotal=20.0),
        ],
    )
    assert order is not None
    assert order.total_amount == 20.0
```

### Pre-Invariants

Pre-invariants validate state *before* a mutation occurs. They are useful for
guard conditions — test that your guard logic correctly rejects invalid
operations:

```python
def test_cannot_modify_shipped_order():
    order = Order(customer_name="Alice", status="SHIPPED")

    with pytest.raises(ValidationError) as exc:
        order.add_item("Another Book", 1, Money(amount=9.99))
    assert "shipped" in str(exc.value.messages)
```

## Testing Domain Services

Domain services encapsulate business rules that span multiple aggregates. Test
them by providing the required aggregates and verifying the outcome.

```python
from myapp.models import Order, OrderItem, Inventory
from myapp.services import OrderFulfillmentService


def test_order_fulfillment():
    order = Order(
        customer_name="Alice",
        items=[OrderItem(book_title="Dune", quantity=2)],
    )
    inventory = Inventory(book_id="1", title="Dune", quantity=10)

    service = OrderFulfillmentService(order, [inventory])
    service.fulfill()

    assert order.status == "CONFIRMED"
    assert inventory.quantity == 8  # 10 - 2
```

### Domain Service Invariants

Domain services can also have pre-invariants. Test that they reject invalid
input:

```python
def test_fulfillment_rejects_out_of_stock():
    order = Order(
        customer_name="Alice",
        items=[OrderItem(book_title="Dune", quantity=20)],
    )
    inventory = Inventory(book_id="1", title="Dune", quantity=5)

    with pytest.raises(ValidationError) as exc:
        service = OrderFulfillmentService(order, [inventory])
        service.fulfill()
    assert "not in stock" in str(exc.value.messages)
```

## Organizing Domain Model Tests

A recommended directory structure:

```
tests/
├── conftest.py              # Domain fixture
├── test_book.py             # Aggregate tests
├── test_order.py            # Aggregate + entity tests
├── test_money.py            # Value object tests
├── test_fulfillment.py      # Domain service tests
└── ...
```

Group tests by the aggregate or concept they exercise. Each test file imports
the elements it needs from your application code.
