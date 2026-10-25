# Aggregate Test Patterns

Patterns for testing user-written business logic in aggregates, entities, and value objects. These are domain unit tests: they call aggregate methods directly, with no handlers, repositories, or infrastructure. [assets/scaffold_aggregate_unit.py](../assets/scaffold_aggregate_unit.py) is the complete example: an Order with entities, value objects, and invariants.

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
from decimal import Decimal as D


def test_place_transitions_to_placed(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=D("10.00"))
    order._events.clear()  # Clear factory events
    order.place()
    assert order.status == "placed"

def test_place_raises_order_placed(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=D("10.00"))
    order._events.clear()
    order.place()
    assert len(order._events) == 1
    assert isinstance(order._events[0], OrderPlaced)
```

## Testing business rules in methods

In the Order example, `place()` raises `ValueError` for an order that is not a draft, and the post-invariant raises `ValidationError` for an order with no items. Test that a rejected call leaves the state unchanged:

```python
def test_state_unchanged_on_failure(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=1, unit_price=D("5.00"))
    order.place()
    original_status = order.status
    with pytest.raises(ValueError, match="Cannot place order in 'placed' status"):
        order.place()
    assert order.status == original_status  # Unchanged
```

## Testing entity management

Entities are tested through their parent aggregate:

```python
def test_add_item(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=D("10.00"))
    assert len(order.line_items) == 1
    assert order.line_items[0].product_id == "p-1"

def test_remove_item(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=D("10.00"))
    order.remove_item("p-1")
    assert len(order.line_items) == 0

def test_computed_properties(self):
    order = Order.create(customer_id="cust-1")
    order.add_item(product_id="p-1", quantity=2, unit_price=D("10.00"))
    order.add_item(product_id="p-2", quantity=1, unit_price=D("25.00"))
    assert order.total == D("45.00")
```

## Testing value object custom operations

Test only the **user-defined methods** on a VO:

```python
def test_money_add_same_currency(self):
    m1 = Money(amount=10.0, currency="USD")
    m2 = Money(amount=20.0, currency="USD")
    result = m1.add(m2)
    assert result.amount == D("30.00")
    assert result.currency == "USD"

def test_money_add_different_currency_fails(self):
    m1 = Money(amount=10.0, currency="USD")
    m2 = Money(amount=20.0, currency="EUR")
    # Money.add() raises ValueError for mixed currencies.
    with pytest.raises(ValueError, match="Cannot add USD and EUR"):
        m1.add(m2)
```
