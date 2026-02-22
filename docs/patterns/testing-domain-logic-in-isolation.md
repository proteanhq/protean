# Testing Domain Logic in Isolation

## The Problem

A developer writes tests for an order placement feature:

```python
class TestPlaceOrder:

    def test_place_order(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderItem, part_of=Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(OrderCommandHandler, part_of=Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            command = PlaceOrder(
                order_id="ord-123",
                customer_id="cust-456",
                items=[{"product_id": "p-1", "quantity": 2, "unit_price": 10.0}],
                total=20.0,
            )
            test_domain.process(command)

            repo = test_domain.repository_for(Order)
            order = repo.get("ord-123")
            assert order.status == "placed"
            assert order.total == 20.0
```

This test works, but it tests the entire pipeline: command deserialization,
handler dispatch, repository operations, and aggregate behavior -- all in one
test. When it fails, which part broke? The test doesn't tell you. It requires
registering multiple domain elements, initializing the domain, and managing
a domain context. It's slow relative to a unit test and tests more than it
intends to.

The deeper problem: when tests can only exercise business logic through the
handler pipeline, developers write fewer tests. The setup overhead discourages
testing edge cases, boundary conditions, and specific business rules. The domain
model -- the most important part of the system -- ends up being the least
tested.

---

## The Pattern

Test domain logic **directly on domain objects** -- aggregates, value objects,
entities, and domain services -- without handlers, repositories, commands, or
infrastructure. These are **unit tests** that exercise business rules in
isolation.

```
Integration test (whole pipeline):
  Command → Handler → Repository → Aggregate → Event → Database
  (tests the plumbing)

Unit test (domain in isolation):
  Aggregate → call method → assert state
  (tests the business logic)
```

Both types of tests are valuable. But domain unit tests should be the
**majority** of your test suite because they test the most important code
(business rules) with the least overhead (no infrastructure).

### Test Setup

The examples below assume a `conftest.py` that uses Protean's `DomainFixture`
to initialize the domain and provide a per-test context:

```python
# tests/conftest.py
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

With this setup, every test runs within an active domain context and all
data is reset between tests automatically.

---

## Testing Aggregates

### Basic State Changes

Test aggregate methods by constructing an aggregate, calling a method, and
asserting the resulting state:

```python
class TestOrderPlacement:

    def test_placing_a_draft_order(self, test_domain):
        order = Order(
            customer_id="cust-123",
            status="draft",
            total=50.0,
        )
        order.items.add(OrderItem(
            product_id="prod-1",
            quantity=2,
            unit_price=25.0,
        ))

        order.place()

        assert order.status == "placed"
        assert order.placed_at is not None

    def test_placing_an_already_placed_order_fails(self, test_domain):
        order = Order(
            customer_id="cust-123",
            status="placed",
            total=50.0,
        )

        with pytest.raises(ValidationError) as exc:
            order.place()

        assert "Only draft orders can be placed" in str(exc.value)
        assert order.status == "placed"  # State unchanged
```

No repository, no handler, no command. Just the aggregate and its behavior.

### Preconditions and Business Rules

Each business rule gets its own test:

```python
class TestAccountWithdrawal:

    def test_successful_withdrawal(self, test_domain):
        account = Account(balance=1000.0, overdraft_limit=50.0)

        account.withdraw(200.0)

        assert account.balance == 800.0

    def test_withdrawal_respects_overdraft_limit(self, test_domain):
        account = Account(balance=100.0, overdraft_limit=50.0)

        # Can withdraw up to balance + overdraft
        account.withdraw(150.0)
        assert account.balance == -50.0

    def test_withdrawal_exceeding_overdraft_fails(self, test_domain):
        account = Account(balance=100.0, overdraft_limit=50.0)

        with pytest.raises(ValidationError) as exc:
            account.withdraw(200.0)

        assert "Insufficient funds" in str(exc.value)
        assert account.balance == 100.0  # State unchanged

    def test_negative_withdrawal_fails(self, test_domain):
        account = Account(balance=1000.0)

        with pytest.raises(ValidationError) as exc:
            account.withdraw(-50.0)

        assert "must be positive" in str(exc.value)

    def test_withdrawal_from_frozen_account_fails(self, test_domain):
        account = Account(balance=1000.0, status="frozen")

        with pytest.raises(ValidationError) as exc:
            account.withdraw(100.0)

        assert "non-active account" in str(exc.value)
```

Five tests, each targeting a specific business rule. Each runs in
milliseconds. Together, they comprehensively test the withdrawal behavior.

### Domain Events

Verify that aggregate methods raise the correct events:

```python
class TestOrderEvents:

    def test_placing_order_raises_order_placed(self, test_domain):
        order = Order(
            customer_id="cust-123",
            total=100.0,
        )
        order.items.add(OrderItem(
            product_id="prod-1",
            quantity=1,
            unit_price=100.0,
        ))

        order.place()

        assert len(order._events) == 1
        event = order._events[0]
        assert isinstance(event, OrderPlaced)
        assert event.order_id == order.order_id
        assert event.customer_id == "cust-123"
        assert event.total == 100.0

    def test_cancelling_shipped_order_raises_shipment_intercept(self, test_domain):
        order = Order(
            customer_id="cust-123",
            status="shipped",
            tracking_number="TRK-789",
        )

        order.cancel("Customer changed mind")

        events = order._events
        assert len(events) == 2
        assert isinstance(events[0], OrderCancelled)
        assert isinstance(events[1], ShipmentInterceptRequested)
        assert events[1].tracking_number == "TRK-789"

    def test_no_event_raised_when_operation_fails(self, test_domain):
        order = Order(status="draft")

        with pytest.raises(ValidationError):
            order.ship("TRK-123")

        assert len(order._events) == 0  # No events on failure
```

The `_events` list on the aggregate collects events raised via `raise_()`.
This allows direct inspection without infrastructure.

---

## Testing Value Objects

### Construction and Validation

```python
class TestMoney:

    def test_valid_money(self, test_domain):
        money = Money(amount=100.0, currency="USD")

        assert money.amount == 100.0
        assert money.currency == "USD"

    def test_negative_amount_rejected(self, test_domain):
        with pytest.raises(ValidationError) as exc:
            Money(amount=-10.0, currency="USD")

        assert "cannot be negative" in str(exc.value)

    def test_invalid_currency_rejected(self, test_domain):
        with pytest.raises(ValidationError) as exc:
            Money(amount=10.0, currency="XYZ")

        assert "Invalid currency" in str(exc.value)

    def test_zero_amount_allowed(self, test_domain):
        money = Money(amount=0.0, currency="USD")
        assert money.amount == 0.0
```

### Equality

```python
class TestMoneyEquality:

    def test_same_values_are_equal(self, test_domain):
        money1 = Money(amount=100.0, currency="USD")
        money2 = Money(amount=100.0, currency="USD")
        assert money1 == money2

    def test_different_amounts_are_not_equal(self, test_domain):
        money1 = Money(amount=100.0, currency="USD")
        money2 = Money(amount=200.0, currency="USD")
        assert money1 != money2

    def test_different_currencies_are_not_equal(self, test_domain):
        money1 = Money(amount=100.0, currency="USD")
        money2 = Money(amount=100.0, currency="EUR")
        assert money1 != money2
```

### Operations

```python
class TestMoneyOperations:

    def test_adding_same_currency(self, test_domain):
        result = Money(amount=30.0, currency="USD").add(
            Money(amount=20.0, currency="USD")
        )
        assert result == Money(amount=50.0, currency="USD")

    def test_adding_different_currencies_fails(self, test_domain):
        with pytest.raises(ValidationError) as exc:
            Money(amount=30.0, currency="USD").add(
                Money(amount=20.0, currency="EUR")
            )
        assert "Cannot add different currencies" in str(exc.value)


class TestDateRange:

    def test_contains_date(self, test_domain):
        range_ = DateRange(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        )
        assert range_.contains(date(2024, 6, 15)) is True
        assert range_.contains(date(2025, 1, 1)) is False

    def test_overlapping_ranges(self, test_domain):
        range1 = DateRange(start_date=date(2024, 1, 1), end_date=date(2024, 6, 30))
        range2 = DateRange(start_date=date(2024, 4, 1), end_date=date(2024, 12, 31))
        assert range1.overlaps(range2) is True

    def test_non_overlapping_ranges(self, test_domain):
        range1 = DateRange(start_date=date(2024, 1, 1), end_date=date(2024, 3, 31))
        range2 = DateRange(start_date=date(2024, 7, 1), end_date=date(2024, 12, 31))
        assert range1.overlaps(range2) is False
```

### Immutability

```python
class TestValueObjectImmutability:

    def test_value_object_is_immutable(self, test_domain):
        email = Email(address="user@example.com")

        with pytest.raises(IncorrectUsageError):
            email.address = "other@example.com"
```

---

## Testing Invariants

### Post-Invariants

```python
class TestOrderInvariants:

    def test_order_must_have_items_when_placed(self, test_domain):
        order = Order(
            customer_id="cust-123",
            status="placed",
            total=50.0,
        )
        # No items added -- invariant should fire

        with pytest.raises(ValidationError) as exc:
            # Trigger invariant check by modifying the aggregate
            order.status = "placed"

        assert "must have at least one item" in str(exc.value)

    def test_discount_cannot_exceed_total(self, test_domain):
        with pytest.raises(ValidationError) as exc:
            Order(
                customer_id="cust-123",
                total=50.0,
                discount=75.0,
            )
        assert "Discount cannot exceed" in str(exc.value)
```

### Pre-Invariants

```python
class TestAccountInvariants:

    def test_balance_must_be_above_overdraft_limit(self, test_domain):
        account = Account(balance=100.0, overdraft_limit=50.0)

        # This should fail the invariant
        with pytest.raises(ValidationError) as exc:
            account.balance = -100.0  # Below -50 overdraft limit

        assert "below overdraft limit" in str(exc.value)
```

---

## Testing Domain Services

Domain services coordinate logic across aggregates. Test them by passing in
aggregate instances directly:

```python
class TestTransferService:

    def test_valid_transfer(self, test_domain):
        source = Account(balance=1000.0, risk_score=2)
        policy = CreditPolicy(max_transfer_amount=5000.0, max_risk_score=5)

        TransferService.validate_and_debit(
            source=source,
            policy=policy,
            amount=500.0,
            transfer_id="txn-1",
            target_account_id="acc-2",
        )

        assert source.balance == 500.0

    def test_transfer_exceeding_policy_limit(self, test_domain):
        source = Account(balance=10000.0, risk_score=2)
        policy = CreditPolicy(max_transfer_amount=5000.0, max_risk_score=5)

        with pytest.raises(ValidationError) as exc:
            TransferService.validate_and_debit(
                source=source,
                policy=policy,
                amount=7000.0,
                transfer_id="txn-1",
                target_account_id="acc-2",
            )

        assert "Exceeds policy limit" in str(exc.value)
        assert source.balance == 10000.0  # Not debited

    def test_transfer_with_high_risk_score(self, test_domain):
        source = Account(balance=1000.0, risk_score=8)
        policy = CreditPolicy(max_transfer_amount=5000.0, max_risk_score=5)

        with pytest.raises(ValidationError) as exc:
            TransferService.validate_and_debit(
                source=source,
                policy=policy,
                amount=100.0,
                transfer_id="txn-1",
                target_account_id="acc-2",
            )

        assert "risk score exceeds" in str(exc.value)
```

No repositories, no handlers. Construct the aggregates, pass them to the
service, assert results.

---

## Testing Entities Within Aggregates

```python
class TestOrderItems:

    def test_adding_items(self, test_domain):
        order = Order(customer_id="cust-123")

        order.add_item(
            product_id="prod-1",
            product_name="Widget",
            quantity=2,
            unit_price=15.0,
        )

        assert len(order.items) == 1
        assert order.items[0].product_id == "prod-1"
        assert order.items[0].quantity == 2

    def test_removing_items(self, test_domain):
        order = Order(customer_id="cust-123")
        order.add_item(
            product_id="prod-1",
            product_name="Widget",
            quantity=2,
            unit_price=15.0,
        )

        order.remove_item("prod-1")

        assert len(order.items) == 0

    def test_updating_item_quantity(self, test_domain):
        order = Order(customer_id="cust-123")
        order.add_item(
            product_id="prod-1",
            product_name="Widget",
            quantity=2,
            unit_price=15.0,
        )

        order.update_item_quantity("prod-1", 5)

        assert order.items[0].quantity == 5
```

Entities are tested through their parent aggregate, which is how they're
accessed in production.

---

## When Integration Tests Are Needed

Domain unit tests don't replace integration tests. They complement them.
Integration tests verify that the pipeline works end-to-end:

### Repository Integration

```python
class TestOrderPersistence:

    def test_order_round_trips_through_repository(self, test_domain):
        test_domain.register(Order)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            repo = test_domain.repository_for(Order)

            order = Order(
                customer_id="cust-123",
                total=100.0,
                status="placed",
            )
            repo.add(order)

            retrieved = repo.get(order.order_id)
            assert retrieved.customer_id == "cust-123"
            assert retrieved.total == 100.0
            assert retrieved.status == "placed"
```

### Handler Pipeline

```python
class TestOrderCommandHandlerIntegration:

    def test_place_order_through_handler(self, test_domain):
        # Register all elements needed for the pipeline
        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(OrderCommandHandler, part_of=Order)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            test_domain.process(PlaceOrder(
                order_id="ord-123",
                customer_id="cust-456",
                items=[{"product_id": "p-1", "quantity": 1, "unit_price": 50.0}],
                total=50.0,
            ))

            order = test_domain.repository_for(Order).get("ord-123")
            assert order.status == "placed"
```

### Event Handler Integration

```python
class TestInventoryReservationIntegration:

    def test_order_placed_triggers_reservation(self, test_domain):
        # Register all elements for the event flow
        test_domain.register(Order)
        test_domain.register(Inventory)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(InventoryEventHandler, part_of=Inventory)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            # Set up inventory
            inventory_repo = test_domain.repository_for(Inventory)
            inventory = Inventory(product_id="prod-1", available_quantity=100)
            inventory_repo.add(inventory)

            # Simulate the event
            event = OrderPlaced(
                order_id="ord-123",
                customer_id="cust-456",
                items=[{"product_id": "prod-1", "quantity": 5}],
                total=50.0,
            )

            handler = InventoryEventHandler()
            handler.on_order_placed(event)

            updated = inventory_repo.get("prod-1")
            assert updated.available_quantity == 95
```

---

## The Testing Pyramid

```
                    /\
                   /  \
                  / E2E \        Few: Full system with real databases
                 /--------\
                /Integration\    Some: Handler + repo + domain
               /--------------\
              /  Domain Unit    \ Many: Aggregates, VOs, services
             /____________________\
```

- **Domain unit tests (base):** Fast, focused, comprehensive. Test every
  business rule, every edge case, every state transition. These are your
  primary tests.

- **Integration tests (middle):** Verify that the pipeline works. Test that
  commands flow through handlers, aggregates are persisted correctly, and
  events are delivered to handlers.

- **End-to-end tests (top):** Verify the full system with real databases
  and brokers. Test critical paths only -- these are slow and brittle.

The domain unit tests should be the **majority** of your test suite because
they test the most important code with the least overhead.

---

## Summary

| Test Type | What It Tests | Setup Needed | Speed | Coverage Goal |
|-----------|--------------|-------------|-------|---------------|
| Domain unit | Business rules, invariants, state changes | Just the aggregate | Very fast | Comprehensive |
| Value object | Concept rules, equality, operations | Just the VO | Very fast | All validations |
| Domain service | Cross-aggregate coordination | Aggregates (no repos) | Very fast | All paths |
| Integration | Handler + repo pipeline | Domain registration | Medium | Critical paths |
| End-to-end | Full system behavior | Real infrastructure | Slow | Happy paths |

The principle: **domain logic is the most important code in your system. Test
it directly, without infrastructure, in isolation. Construct aggregates, call
methods, assert results. Save integration tests for verifying the plumbing.**

!!!tip "Run all test layers in both modes"
    Domain unit tests already use in-memory adapters. Integration tests can
    too -- with Protean's [Dual-Mode Testing](dual-mode-testing.md), a single
    `pytest --protean-env memory` flag switches every adapter to its in-memory
    equivalent. Run fast during development, then validate against real
    infrastructure in CI.

---

!!! tip "Related reading"
    **Concepts:**

    - [Aggregates](../core-concepts/domain-elements/aggregates.md) — Aggregate structure and invariants.
    - [Value Objects](../core-concepts/domain-elements/value-objects.md) — Testing immutable domain concepts.

    **Guides:**

    - [Domain Model Tests](../guides/testing/domain-model-tests.md) — Unit testing aggregates, entities, and value objects.
    - [Fixtures and Patterns](../guides/testing/fixtures-and-patterns.md) — Reusable pytest fixtures and test recipes.
