# Aggregate Test Patterns

Patterns for testing user-written business logic in aggregates, entities, and value objects.

## Overview

Domain unit tests are the base of the testing pyramid. They test aggregate methods, invariants, and event raising directly — no handlers, repositories, or infrastructure.

## Code

Complete examples are in:
- [assets/scaffold_aggregate_unit.py](../assets/scaffold_aggregate_unit.py) — Order with entities, value objects, invariants

## Testing factory methods

Factory methods (classmethods) create aggregate instances and typically raise events. Test both the resulting state and the events:

```python
def test_factory_sets_correct_state(self):
    order = Order.create(customer_id="cust-1")
    assert order.customer_id == "cust-1"
    assert order.status == "draft"  # default state

def test_factory_raises_event(self):
    account = Account.register(username="alice", email="a@test.com")
    assert len(account._events) == 1
    assert isinstance(account._events[0], AccountRegistered)

def test_factory_event_carries_correct_data(self):
    account = Account.register(username="alice", email="a@test.com")
    event = account._events[0]
    assert event.account_id == account.id
    assert event.username == "alice"
```

## Testing state transition methods

Test the before/after state and events. Use `_events.clear()` when a prior factory already raised events:

```python
def test_place_transitions_to_placed(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=10.0)
    order._events.clear()  # Clear factory events
    order.place()
    assert order.status == "placed"

def test_place_raises_order_placed(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=10.0)
    order._events.clear()
    order.place()
    assert len(order._events) == 1
    assert isinstance(order._events[0], OrderPlaced)
```

## Testing user-defined invariants

Invariants defined with `@invariant.pre` and `@invariant.post` are user business rules. Test that they fire correctly:

```python
def test_invariant_rejects_invalid_state(self):
    """Placed orders must have items (post-invariant)."""
    order = Order.create(customer_id="cust-1")
    with pytest.raises(ValidationError):
        order.place()  # No items — invariant fires
```

## Testing business rules in methods

Methods that guard against invalid operations with `ValueError` or `ValidationError`:

```python
def test_cannot_place_already_placed_order(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=1, unit_price=5.0)
    order.place()
    with pytest.raises(ValueError):
        order.place()  # Already placed

def test_state_unchanged_on_failure(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=1, unit_price=5.0)
    order.place()
    original_status = order.status
    with pytest.raises(ValueError):
        order.place()
    assert order.status == original_status  # Unchanged
```

## Testing entity management

Entities are tested through their parent aggregate:

```python
def test_add_item(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=10.0)
    assert len(order.line_items) == 1
    assert order.line_items[0].product_id == "p-1"

def test_remove_item(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=10.0)
    order.remove_item("p-1")
    assert len(order.line_items) == 0

def test_computed_properties(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=10.0)
    order.add_item(product_id="p-2", quantity=1, unit_price=25.0)
    assert order.total == 45.0
```

## Testing value object custom operations

Only test **user-defined methods** on VOs, not construction/equality/immutability (which Protean guarantees):

```python
def test_money_add_same_currency(self):
    m1 = Money(amount=10.0, currency="USD")
    m2 = Money(amount=20.0, currency="USD")
    result = m1.add(m2)
    assert result.amount == 30.0
    assert result.currency == "USD"

def test_money_add_different_currency_fails(self):
    m1 = Money(amount=10.0, currency="USD")
    m2 = Money(amount=20.0, currency="EUR")
    with pytest.raises(ValueError):
        m1.add(m2)
```

## Avoid mocks — use real domain elements

Always construct real aggregates, entities, and value objects directly in tests. Protean's in-memory infrastructure means there is no need to mock repositories or domain elements. Mocks hide bugs and make tests brittle. Only mock truly external dependencies (third-party HTTP APIs) that have no in-memory substitute.

## What NOT to test

- VO construction with valid data (framework guarantee)
- VO equality (`money1 == money2`) (framework guarantee)
- VO immutability (`money.amount = 5` raises error) (framework guarantee)
- Field validation (`required=True`, `max_length`) (Protean Layer 1)
- Element registration in domain registry (framework guarantee)
