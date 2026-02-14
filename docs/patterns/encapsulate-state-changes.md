# Encapsulate State Changes in Named Methods

## The Problem

A developer writes a command handler to ship an order:

```python
@handle(ShipOrder)
def ship_order(self, command: ShipOrder):
    repo = current_domain.repository_for(Order)
    order = repo.get(command.order_id)

    order.status = "shipped"
    order.shipped_at = datetime.now(timezone.utc)
    order.tracking_number = command.tracking_number

    repo.add(order)
```

It works. The test passes. Six months later, a new business rule arrives:
"Orders can only be shipped if they have been paid." The developer adds an
`if` check to the handler. A month after that: "Premium orders should send a
priority notification when shipped." Another `if` in the handler. Then:
"International orders need customs documentation before shipping." More
conditions, more logic, spread across the handler.

The aggregate has become a data bag. The handler has become the brain. This is
the **anemic domain model** -- the most pervasive anti-pattern in DDD.

The problems are structural:

- **Business rules scatter across handlers.** The rules about shipping live in
  the command handler, the event handler that processes returns, the application
  service that handles admin overrides, and the batch job that auto-ships
  after payment confirmation. Each location has its own version of the rules.

- **Invariants can't protect the aggregate.** Protean's `@invariant.post`
  decorator runs after methods are called on the aggregate. But if the handler
  sets fields directly, the aggregate's methods are never called, and
  invariants become the only defense. Invariants catch violations after the
  fact -- they can't encode the business process itself.

- **The ubiquitous language disappears.** The business says "ship an order."
  The code says `order.status = "shipped"`. The verb -- the business intent --
  is lost. When reading the code, you see mechanical field assignments, not
  business operations.

- **Events are an afterthought.** Domain events should be raised as part of
  the business operation. When the handler sets fields and then manually raises
  an event, the event is disconnected from the state change it represents.
  Forgetting to raise the event becomes a likely bug.

- **Testing requires infrastructure.** To test the business rules of shipping,
  you must set up the handler, the repository, the command, and the UoW. The
  business logic can't be tested by simply calling a method on the aggregate.

The root cause: **the aggregate exposes its state for direct manipulation
instead of expressing behavior through methods**.

---

## The Pattern

Encapsulate every state change in a **named method** on the aggregate that
expresses business intent. The method validates preconditions, performs the
state change, enforces invariants, and raises domain events -- all in one
place.

```
Anti-pattern (handler sets fields):
  Handler:  order.status = "shipped"
            order.shipped_at = now()
            order.tracking_number = "TRK-123"
            order.raise_(OrderShipped(...))

Pattern (aggregate method):
  Handler:  order.ship(tracking_number="TRK-123")
  Aggregate method internally:
            validates preconditions
            sets status, shipped_at, tracking_number
            raises OrderShipped event
```

The handler becomes a thin bridge between the command and the aggregate method.
The aggregate method becomes the single source of truth for the business
operation.

### The Name Is the Ubiquitous Language

Method names should come from the domain's ubiquitous language:

| Business Operation | Method Name | NOT |
|-------------------|-------------|-----|
| Ship an order | `order.ship()` | `order.set_status("shipped")` |
| Cancel a subscription | `subscription.cancel()` | `subscription.status = "cancelled"` |
| Approve a loan | `loan.approve(approved_by)` | `loan.is_approved = True` |
| Withdraw money | `account.withdraw(amount)` | `account.balance -= amount` |
| Enroll a student | `course.enroll(student_id)` | `course.students.append(student_id)` |
| Archive a project | `project.archive()` | `project.archived = True` |

When a domain expert reads the code, they should recognize the operations
without needing to understand the field-level mechanics.

---

## Applying the Pattern

### Before: Direct Field Manipulation

```python
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total: Float(default=0.0)
    shipped_at: DateTime()
    tracking_number: String()
    cancelled_at: DateTime()
    cancellation_reason: String()


@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(ShipOrder)
    def ship_order(self, command: ShipOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)

        # Business logic is in the handler, not the aggregate
        if order.status != "paid":
            raise ValidationError(
                {"status": ["Only paid orders can be shipped"]}
            )

        if not order.items:
            raise ValidationError(
                {"items": ["Cannot ship an order with no items"]}
            )

        order.status = "shipped"
        order.shipped_at = datetime.now(timezone.utc)
        order.tracking_number = command.tracking_number

        order.raise_(OrderShipped(
            order_id=order.order_id,
            customer_id=order.customer_id,
            tracking_number=command.tracking_number,
        ))

        repo.add(order)

    @handle(CancelOrder)
    def cancel_order(self, command: CancelOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)

        # Same pattern: business logic in the handler
        if order.status in ("shipped", "cancelled"):
            raise ValidationError(
                {"status": ["Cannot cancel a shipped or already cancelled order"]}
            )

        order.status = "cancelled"
        order.cancelled_at = datetime.now(timezone.utc)
        order.cancellation_reason = command.reason

        order.raise_(OrderCancelled(
            order_id=order.order_id,
            customer_id=order.customer_id,
            reason=command.reason,
        ))

        repo.add(order)
```

Problems with this approach:
- The handler validates, mutates, and raises events -- three responsibilities
- The shipping rules are duplicated if another handler also ships orders
- Testing requires constructing commands and running through the handler
- The aggregate has no behavior; it's a data structure

### After: Named Methods on the Aggregate

```python
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total: Float(default=0.0)
    shipped_at: DateTime()
    tracking_number: String()
    cancelled_at: DateTime()
    cancellation_reason: String()

    def ship(self, tracking_number: str) -> None:
        """Ship this order with the given tracking number."""
        if self.status != "paid":
            raise ValidationError(
                {"status": ["Only paid orders can be shipped"]}
            )

        if not self.items:
            raise ValidationError(
                {"items": ["Cannot ship an order with no items"]}
            )

        self.status = "shipped"
        self.shipped_at = datetime.now(timezone.utc)
        self.tracking_number = tracking_number

        self.raise_(OrderShipped(
            order_id=self.order_id,
            customer_id=self.customer_id,
            tracking_number=tracking_number,
        ))

    def cancel(self, reason: str) -> None:
        """Cancel this order with the given reason."""
        if self.status in ("shipped", "cancelled"):
            raise ValidationError(
                {"status": ["Cannot cancel a shipped or already cancelled order"]}
            )

        self.status = "cancelled"
        self.cancelled_at = datetime.now(timezone.utc)
        self.cancellation_reason = reason

        self.raise_(OrderCancelled(
            order_id=self.order_id,
            customer_id=self.customer_id,
            reason=reason,
        ))

    def pay(self) -> None:
        """Mark this order as paid."""
        if self.status != "draft":
            raise ValidationError(
                {"status": ["Only draft orders can be paid"]}
            )

        self.status = "paid"

        self.raise_(OrderPaid(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total=self.total,
        ))


@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(ShipOrder)
    def ship_order(self, command: ShipOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.ship(command.tracking_number)
        repo.add(order)

    @handle(CancelOrder)
    def cancel_order(self, command: CancelOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.cancel(command.reason)
        repo.add(order)

    @handle(PayOrder)
    def pay_order(self, command: PayOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.pay()
        repo.add(order)
```

Now the handler is three lines: load, call, save. All business logic --
precondition validation, state mutation, and event raising -- is in the
aggregate where it belongs.

---

## The Three Responsibilities of an Aggregate Method

Every state-changing method on an aggregate should handle three things:

### 1. Validate Preconditions

Check whether the operation is allowed given the aggregate's current state:

```python
def ship(self, tracking_number: str) -> None:
    # Precondition: order must be in "paid" status
    if self.status != "paid":
        raise ValidationError(
            {"status": ["Only paid orders can be shipped"]}
        )
```

Preconditions are different from invariants. Preconditions check whether the
operation *can* be performed. Invariants check whether the aggregate's state
*is valid* after the operation. Both are important, but preconditions belong
at the top of the method.

### 2. Mutate State

Perform the actual field changes:

```python
    self.status = "shipped"
    self.shipped_at = datetime.now(timezone.utc)
    self.tracking_number = tracking_number
```

All related field changes happen together in the same method. This prevents
the "forgot to set shipped_at when setting status to shipped" bug that occurs
when handlers manage field assignments independently.

### 3. Raise Domain Events

Record what happened as a domain event:

```python
    self.raise_(OrderShipped(
        order_id=self.order_id,
        customer_id=self.customer_id,
        tracking_number=tracking_number,
    ))
```

The event is raised as part of the business operation, not as an afterthought
in the handler. This guarantees that whenever the state changes, the
corresponding event is raised. You can't ship an order without raising
`OrderShipped`.

---

## How Protean Supports This

### Invariants Complement Methods

Protean's `@invariant.post` decorator provides a safety net that works
alongside named methods:

```python
@domain.aggregate
class Account:
    account_id: Auto(identifier=True)
    balance: Float(default=0.0)
    overdraft_limit: Float(default=50.0)

    def withdraw(self, amount: float) -> None:
        """Withdraw the specified amount."""
        if amount <= 0:
            raise ValidationError(
                {"amount": ["Withdrawal amount must be positive"]}
            )
        self.balance -= amount
        self.raise_(MoneyWithdrawn(
            account_id=self.account_id,
            amount=amount,
            new_balance=self.balance,
        ))

    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise ValidationError(
                {"balance": ["Balance cannot be below overdraft limit"]}
            )
```

The `withdraw` method validates its own preconditions (positive amount). The
invariant catches any state that violates the business rule, regardless of how
it was reached. Together, they provide defense in depth.

### Event Sourcing Integration

For event-sourced aggregates, methods and events are even more tightly coupled.
The method raises an event, and the `@apply` handler mutates state:

```python
@domain.aggregate(is_event_sourced=True)
class Account(BaseAggregate):
    account_id: Auto(identifier=True)
    balance: Float(default=0.0)

    def withdraw(self, amount: float) -> None:
        if amount <= 0:
            raise ValidationError(
                {"amount": ["Withdrawal amount must be positive"]}
            )
        if self.balance - amount < 0:
            raise ValidationError(
                {"balance": ["Insufficient funds"]}
            )
        self.raise_(MoneyWithdrawn(
            account_id=self.account_id,
            amount=amount,
        ))

    @apply
    def on_money_withdrawn(self, event: MoneyWithdrawn):
        self.balance -= event.amount
```

In event-sourced aggregates, the method validates and raises the event, while
the `@apply` handler performs the actual mutation. This separation is essential:
the same `@apply` handler replays events when reconstructing the aggregate from
its event stream.

### The `atomic_change` Context Manager

When multiple state changes must happen together without triggering intermediate
invariant checks, Protean provides `atomic_change`:

```python
from protean.core.aggregate import atomic_change


def restructure_order(self, new_items: list, new_total: float) -> None:
    """Replace all items and recalculate total atomically."""
    with atomic_change(self):
        self.items.clear()
        for item_data in new_items:
            self.items.add(OrderItem(**item_data))
        self.total = new_total
    # Invariants checked here, after all changes are applied
```

This is still an encapsulated method on the aggregate -- the handler doesn't
need to know about `atomic_change`. It calls `order.restructure_order(...)`,
and the aggregate handles the complexity internally.

---

## The Command-Method Connection

Commands name the intent. Methods execute it. The handler is the bridge.

```
Command:     ShipOrder(order_id, tracking_number)
                    ↓
Handler:     order = repo.get(command.order_id)
             order.ship(command.tracking_number)  ← one line
             repo.add(order)
                    ↓
Method:      Order.ship(tracking_number)
             - validates preconditions
             - mutates state
             - raises OrderShipped event
```

The naming should be consistent:

| Command | Method | Event |
|---------|--------|-------|
| `PlaceOrder` | `order.place()` | `OrderPlaced` |
| `ShipOrder` | `order.ship(tracking)` | `OrderShipped` |
| `CancelOrder` | `order.cancel(reason)` | `OrderCancelled` |
| `ApproveRefund` | `refund.approve(approver)` | `RefundApproved` |
| `SuspendAccount` | `account.suspend(reason)` | `AccountSuspended` |
| `WithdrawMoney` | `account.withdraw(amount)` | `MoneyWithdrawn` |

The command verb, the method name, and the event name all express the same
business operation in different tenses: imperative (command), present
(method), past (event).

---

## Common Anti-Patterns

### Setter Methods Disguised as Business Methods

```python
# Anti-pattern: setters with business names
class Order:
    def set_shipped(self, tracking_number):
        self.status = "shipped"
        self.tracking_number = tracking_number
```

This is just a setter with a fancy name. It doesn't validate preconditions,
doesn't raise events, and doesn't express the full business operation. A real
method captures the complete behavior.

### God Method That Does Everything

```python
# Anti-pattern: one method handles all state transitions
class Order:
    def update_status(self, new_status, **kwargs):
        if new_status == "shipped":
            self.status = "shipped"
            self.tracking_number = kwargs.get("tracking_number")
            # ... shipping logic
        elif new_status == "cancelled":
            self.status = "cancelled"
            self.cancellation_reason = kwargs.get("reason")
            # ... cancellation logic
        elif new_status == "paid":
            # ... payment logic
```

Each business operation should be its own method. `ship()`, `cancel()`, and
`pay()` are different operations with different preconditions, different
state changes, and different events. Merging them into a generic
`update_status` loses the ubiquitous language and creates a maintenance
nightmare.

### Business Logic in Constructors

```python
# Anti-pattern: complex logic in __init__ or creation
class Order:
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Don't put complex business logic here
        if self.customer_type == "premium":
            self.apply_premium_discount()
        self.calculate_tax()
        self.raise_(OrderCreated(...))
```

Protean's `defaults()` method is the right place for conditional default
values. For business operations at creation time, use a class method or a
separate `place()` / `create()` method that the handler calls after
construction:

```python
class Order:
    def defaults(self):
        """Set conditional defaults at initialization."""
        if not self.total:
            self.total = sum(item.line_total for item in self.items)

    def place(self):
        """Business operation: place the order."""
        self.status = "placed"
        self.placed_at = datetime.now(timezone.utc)
        self.raise_(OrderPlaced(...))
```

---

## Testing Benefits

Encapsulated methods make domain logic directly testable without infrastructure:

```python
class TestOrderShipping:

    def test_shipping_a_paid_order(self, test_domain):
        order = Order(
            customer_id="cust-1",
            items=[OrderItem(product_id="prod-1", quantity=1, unit_price=10.0)],
            status="paid",
        )

        order.ship(tracking_number="TRK-123")

        assert order.status == "shipped"
        assert order.tracking_number == "TRK-123"
        assert order.shipped_at is not None
        assert len(order._events) == 1
        assert isinstance(order._events[0], OrderShipped)

    def test_cannot_ship_unpaid_order(self, test_domain):
        order = Order(
            customer_id="cust-1",
            items=[OrderItem(product_id="prod-1", quantity=1, unit_price=10.0)],
            status="draft",
        )

        with pytest.raises(ValidationError) as exc:
            order.ship(tracking_number="TRK-123")

        assert "Only paid orders can be shipped" in str(exc.value)
        assert order.status == "draft"  # State unchanged

    def test_cannot_ship_empty_order(self, test_domain):
        order = Order(customer_id="cust-1", status="paid")

        with pytest.raises(ValidationError) as exc:
            order.ship(tracking_number="TRK-123")

        assert "Cannot ship an order with no items" in str(exc.value)
```

No repository, no command, no handler, no UoW. Just construct the aggregate,
call the method, assert the result. This is fast, focused, and comprehensive.

---

## When Not to Use This Pattern

### Simple CRUD Without Business Rules

If an aggregate is genuinely a data container with no business rules -- no
state machine, no preconditions, no events -- direct field assignment is
acceptable. But this is rare in a DDD system. If most of your aggregates
look like data bags, consider whether DDD is the right approach for your
domain.

### Bulk Data Loading

When hydrating aggregates from a database or event stream, the framework sets
fields directly. This is internal framework behavior, not application-level
code. Protean handles this transparently.

### Value Objects

Value objects are immutable. They don't have state-changing methods in the same
sense. You replace a value object rather than mutating it:

```python
# Value objects are replaced, not mutated
order.shipping_address = ShippingAddress(
    street="456 Oak Ave",
    city="Springfield",
    state="IL",
    postal_code="62701",
    country="US",
)
```

This is not a business method because the aggregate might have a method that
wraps this replacement with validation:

```python
def update_shipping_address(self, new_address: ShippingAddress) -> None:
    if self.status != "draft":
        raise ValidationError(
            {"status": ["Cannot change address after order is placed"]}
        )
    self.shipping_address = new_address
```

---

## Summary

| Aspect | Direct Field Assignment | Named Methods |
|--------|------------------------|---------------|
| Business logic location | Scattered in handlers | Centralized in aggregate |
| Precondition checking | Handler's responsibility | Method's responsibility |
| Event raising | Manual, easy to forget | Automatic, part of the operation |
| Ubiquitous language | Lost (`status = "shipped"`) | Preserved (`order.ship()`) |
| Invariant protection | Only post-hoc | Preconditions + invariants |
| Testability | Requires handler + infra | Direct method calls |
| Duplication risk | High (multiple handlers) | None (single method) |
| Code readability | Mechanical field updates | Business-intent method calls |

The principle: **aggregates express behavior through named methods. Handlers
orchestrate. The aggregate is the authority on its own state transitions.**
