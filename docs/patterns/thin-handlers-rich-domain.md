# Thin Handlers, Rich Domain

## The Problem

A developer writes a command handler for processing refunds:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(RequestRefund)
    def request_refund(self, command: RequestRefund):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)

        # Check if the order is eligible for refund
        if order.status not in ("shipped", "delivered"):
            raise ValidationError(
                {"status": ["Only shipped or delivered orders can be refunded"]}
            )

        # Check if the refund window has passed
        if order.delivered_at:
            days_since_delivery = (datetime.now(timezone.utc) - order.delivered_at).days
            if days_since_delivery > 30:
                raise ValidationError(
                    {"timing": ["Refund window has expired (30 days)"]}
                )

        # Calculate the refund amount
        refund_amount = order.total
        if order.partial_refund_amount:
            refund_amount = order.total - order.partial_refund_amount

        if command.amount and command.amount < refund_amount:
            refund_amount = command.amount

        # Apply the refund
        order.status = "refund_requested"
        order.refund_amount = refund_amount
        order.refund_requested_at = datetime.now(timezone.utc)
        order.refund_reason = command.reason

        # Raise events
        order.raise_(RefundRequested(
            order_id=order.order_id,
            customer_id=order.customer_id,
            amount=refund_amount,
            reason=command.reason,
        ))

        # Check if we need to notify the warehouse
        if order.status == "shipped" and not order.delivered_at:
            order.raise_(ShipmentInterceptRequested(
                order_id=order.order_id,
                tracking_number=order.tracking_number,
            ))

        repo.add(order)
```

This handler is 40 lines of business logic. It validates, calculates, mutates,
decides, and raises events. The `Order` aggregate is a passive data container
that the handler manipulates.

This is the **anemic domain model** -- an anti-pattern where domain objects
carry data but no behavior, and business logic lives in service layers
(handlers, application services, utility functions).

The consequences:

- **Logic duplication.** Another handler that processes admin overrides
  reimplements the refund calculation. A batch job that auto-refunds expired
  subscriptions has its own version. Each diverges slightly over time.

- **Untestable business logic.** To test refund eligibility, you need to
  construct a command, set up a repository, create a handler instance, and run
  it within a UoW. The business rule is buried inside infrastructure.

- **Hidden dependencies.** The handler knows about refund windows, partial
  refunds, shipment interception, and warehouse notifications. These are
  domain concerns scattered across infrastructure code.

- **Aggregate bypass.** Since the aggregate has no methods, nothing prevents
  other code from setting `order.status = "refund_requested"` without
  checking eligibility or raising events.

The root cause: **behavior is in the wrong place**. The handler should
orchestrate; the domain model should think.

---

## The Pattern

Keep handlers **thin** -- they load, delegate, and save. Move all business
logic into **aggregates** and **domain services**.

```
Thin handler:
  1. Load aggregate from repository
  2. Call one aggregate method
  3. Save aggregate to repository

Rich domain:
  - Aggregate methods validate, mutate, and raise events
  - Domain services coordinate cross-aggregate logic
  - Value objects encapsulate concept rules
```

The handler pattern is almost always three lines:

```python
@handle(SomeCommand)
def handle_command(self, command: SomeCommand):
    repo = current_domain.repository_for(Aggregate)
    aggregate = repo.get(command.aggregate_id)
    aggregate.do_the_thing(command.relevant_data)
    repo.add(aggregate)
```

Load. Call. Save. Everything else belongs in the domain model.

---

## Applying the Pattern

### Before: Thick Handler

```python
@handle(RequestRefund)
def request_refund(self, command: RequestRefund):
    repo = current_domain.repository_for(Order)
    order = repo.get(command.order_id)

    # 40 lines of business logic in the handler
    if order.status not in ("shipped", "delivered"):
        raise ValidationError(...)

    days_since = (datetime.now(timezone.utc) - order.delivered_at).days
    if days_since > 30:
        raise ValidationError(...)

    refund_amount = order.total - (order.partial_refund_amount or 0)
    if command.amount and command.amount < refund_amount:
        refund_amount = command.amount

    order.status = "refund_requested"
    order.refund_amount = refund_amount
    order.refund_requested_at = datetime.now(timezone.utc)
    order.refund_reason = command.reason

    order.raise_(RefundRequested(...))

    if order.status == "shipped" and not order.delivered_at:
        order.raise_(ShipmentInterceptRequested(...))

    repo.add(order)
```

### After: Thin Handler, Rich Aggregate

```python
# --- The handler: thin ---
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(RequestRefund)
    def request_refund(self, command: RequestRefund):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.request_refund(
            amount=command.amount,
            reason=command.reason,
        )
        repo.add(order)


# --- The aggregate: rich ---
@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    items = HasMany(OrderItem)
    status = String(default="draft")
    total = Float(default=0.0)
    partial_refund_amount = Float(default=0.0)
    refund_amount = Float()
    refund_reason = String()
    refund_requested_at = DateTime()
    delivered_at = DateTime()
    tracking_number = String()

    REFUND_WINDOW_DAYS = 30

    def request_refund(self, amount: float = None, reason: str = "") -> None:
        """Request a refund for this order."""
        self._validate_refund_eligibility()

        refund_amount = self._calculate_refund_amount(amount)

        self.status = "refund_requested"
        self.refund_amount = refund_amount
        self.refund_requested_at = datetime.now(timezone.utc)
        self.refund_reason = reason

        self.raise_(RefundRequested(
            order_id=self.order_id,
            customer_id=self.customer_id,
            amount=refund_amount,
            reason=reason,
        ))

        if self._needs_shipment_intercept():
            self.raise_(ShipmentInterceptRequested(
                order_id=self.order_id,
                tracking_number=self.tracking_number,
            ))

    def _validate_refund_eligibility(self) -> None:
        """Check if this order can be refunded."""
        if self.status not in ("shipped", "delivered"):
            raise ValidationError(
                {"status": ["Only shipped or delivered orders can be refunded"]}
            )

        if self.delivered_at:
            days_since = (datetime.now(timezone.utc) - self.delivered_at).days
            if days_since > self.REFUND_WINDOW_DAYS:
                raise ValidationError(
                    {"timing": [
                        f"Refund window has expired "
                        f"({self.REFUND_WINDOW_DAYS} days)"
                    ]}
                )

    def _calculate_refund_amount(self, requested_amount: float = None) -> float:
        """Calculate the actual refund amount."""
        max_refundable = self.total - self.partial_refund_amount
        if requested_amount and requested_amount < max_refundable:
            return requested_amount
        return max_refundable

    def _needs_shipment_intercept(self) -> bool:
        """Check if we need to intercept the shipment."""
        return self.status == "shipped" and not self.delivered_at
```

The handler is 5 lines. The aggregate has the business logic organized into
clear, named methods with specific responsibilities.

---

## Where Logic Lives

### Aggregate Methods: Single-Aggregate Business Rules

Logic that depends only on the aggregate's own state belongs in aggregate
methods:

```python
@domain.aggregate
class Account:
    account_id = Auto(identifier=True)
    balance = Float(default=0.0)
    overdraft_limit = Float(default=0.0)
    status = String(default="active")
    daily_withdrawal_total = Float(default=0.0)
    last_withdrawal_date = Date()

    DAILY_WITHDRAWAL_LIMIT = 5000.0

    def withdraw(self, amount: float) -> None:
        """Withdraw money from this account."""
        if self.status != "active":
            raise ValidationError(
                {"status": ["Cannot withdraw from a non-active account"]}
            )

        if amount <= 0:
            raise ValidationError(
                {"amount": ["Withdrawal amount must be positive"]}
            )

        self._check_daily_limit(amount)

        if self.balance - amount < -self.overdraft_limit:
            raise ValidationError(
                {"balance": ["Insufficient funds"]}
            )

        self.balance -= amount
        self._update_daily_total(amount)

        self.raise_(MoneyWithdrawn(
            account_id=self.account_id,
            amount=amount,
            new_balance=self.balance,
        ))

    def _check_daily_limit(self, amount: float) -> None:
        today = date.today()
        if self.last_withdrawal_date != today:
            self.daily_withdrawal_total = 0.0

        if self.daily_withdrawal_total + amount > self.DAILY_WITHDRAWAL_LIMIT:
            raise ValidationError(
                {"amount": [
                    f"Daily withdrawal limit of "
                    f"{self.DAILY_WITHDRAWAL_LIMIT} exceeded"
                ]}
            )

    def _update_daily_total(self, amount: float) -> None:
        today = date.today()
        if self.last_withdrawal_date != today:
            self.daily_withdrawal_total = amount
        else:
            self.daily_withdrawal_total += amount
        self.last_withdrawal_date = today
```

All withdrawal logic -- status check, daily limits, balance check, total
tracking -- is in the aggregate. The handler is:

```python
@handle(WithdrawMoney)
def withdraw(self, command: WithdrawMoney):
    repo = current_domain.repository_for(Account)
    account = repo.get(command.account_id)
    account.withdraw(command.amount)
    repo.add(account)
```

### Domain Services: Cross-Aggregate Coordination

Logic that reads from multiple aggregates but modifies only one belongs in a
domain service:

```python
@domain.domain_service(part_of=[Account, CreditPolicy])
class TransferService:
    """Validates transfer eligibility across Account and CreditPolicy."""

    @classmethod
    def validate_and_debit(
        cls,
        source: Account,
        policy: CreditPolicy,
        amount: float,
        transfer_id: str,
        target_account_id: str,
    ) -> None:
        """Validate the transfer and debit the source account."""
        if amount > policy.max_transfer_amount:
            raise ValidationError(
                {"amount": [
                    f"Exceeds policy limit of {policy.max_transfer_amount}"
                ]}
            )

        if source.risk_score > policy.max_risk_score:
            raise ValidationError(
                {"risk": ["Account risk score exceeds policy threshold"]}
            )

        # Delegate the actual debit to the aggregate
        source.debit(amount, transfer_id, target_account_id)


@domain.command_handler(part_of=Account)
class AccountCommandHandler(BaseCommandHandler):

    @handle(TransferMoney)
    def transfer(self, command: TransferMoney):
        account_repo = current_domain.repository_for(Account)
        policy_repo = current_domain.repository_for(CreditPolicy)

        source = account_repo.get(command.from_account_id)
        policy = policy_repo.get(source.credit_policy_id)

        TransferService.validate_and_debit(
            source=source,
            policy=policy,
            amount=command.amount,
            transfer_id=command.transfer_id,
            target_account_id=command.to_account_id,
        )

        account_repo.add(source)
```

The handler loads both aggregates and calls the domain service. The domain
service coordinates the validation logic. The aggregate's `debit()` method
handles the actual state change. Each component has a clear responsibility.

### Value Objects: Concept-Level Logic

Logic intrinsic to a domain concept belongs in the value object:

```python
@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(max_length=3, required=True)

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValidationError(
                {"currency": ["Cannot add different currencies"]}
            )
        return Money(amount=self.amount + other.amount, currency=self.currency)
```

Currency-matching logic lives in `Money`, not in the handler that adds two
monetary amounts.

---

## The Three-Line Handler Test

If your handler has more than the three canonical lines (load, call, save),
ask whether the extra logic belongs in the domain model:

| Handler Line | Belongs In Handler? | Move To |
|-------------|--------------------|----|
| `repo.get(id)` | Yes | -- |
| `aggregate.method(data)` | Yes | -- |
| `repo.add(aggregate)` | Yes | -- |
| `if aggregate.status != "active"` | No | Aggregate method (precondition) |
| `amount = command.total * 0.9` | No | Aggregate method (calculation) |
| `aggregate.raise_(Event(...))` | No | Aggregate method (event raising) |
| `if user.role != "admin"` | Maybe | Handler (Layer 4 contextual check) |
| `service.validate(a, b)` | Yes | Domain service (cross-aggregate) |

The handler is the **coordinator**, not the **decision-maker**.

---

## Signs Your Handler Is Too Thick

1. **If-else business logic.** Conditional branching based on aggregate state
   should be inside the aggregate.

2. **Calculations.** Computing amounts, percentages, dates, or derived values
   belongs in the aggregate or a domain service.

3. **Multiple aggregate method calls.** If the handler calls several methods
   in sequence on the same aggregate, those methods should be composed into a
   single higher-level method on the aggregate.

4. **Event raising.** Events should be raised inside aggregate methods, not
   in the handler.

5. **Domain knowledge.** If the handler "knows" business rules (refund windows,
   discount calculations, eligibility criteria), that knowledge belongs in the
   domain model.

6. **More than 10 lines of non-infrastructure code.** A handler that's longer
   than load-call-save is a code smell.

---

## Testing Benefits

The most compelling reason for thin handlers: **domain logic becomes directly
testable**.

### Testing with Thick Handlers (Hard)

```python
class TestRefund:

    def test_refund_eligibility(self, test_domain):
        # Must set up: command, handler, repository, UoW
        test_domain.register(Order)
        test_domain.register(OrderCommandHandler)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            # Create and persist an order
            repo = test_domain.repository_for(Order)
            order = Order(status="delivered", total=100.0, delivered_at=datetime.now())
            repo.add(order)

            # Build command
            command = RequestRefund(order_id=order.order_id, reason="Changed mind")

            # Process through handler
            test_domain.process(command)

            # Verify
            updated = repo.get(order.order_id)
            assert updated.status == "refund_requested"
```

### Testing with Thin Handlers (Easy)

```python
class TestRefund:

    def test_can_refund_delivered_order(self, test_domain):
        order = Order(
            status="delivered",
            total=100.0,
            delivered_at=datetime.now(timezone.utc),
        )

        order.request_refund(reason="Changed mind")

        assert order.status == "refund_requested"
        assert order.refund_amount == 100.0
        assert len(order._events) == 1
        assert isinstance(order._events[0], RefundRequested)

    def test_cannot_refund_draft_order(self, test_domain):
        order = Order(status="draft", total=100.0)

        with pytest.raises(ValidationError) as exc:
            order.request_refund(reason="Changed mind")

        assert "Only shipped or delivered orders" in str(exc.value)

    def test_refund_window_expired(self, test_domain):
        order = Order(
            status="delivered",
            total=100.0,
            delivered_at=datetime.now(timezone.utc) - timedelta(days=31),
        )

        with pytest.raises(ValidationError) as exc:
            order.request_refund(reason="Changed mind")

        assert "Refund window has expired" in str(exc.value)

    def test_partial_refund_calculation(self, test_domain):
        order = Order(
            status="delivered",
            total=100.0,
            partial_refund_amount=30.0,
            delivered_at=datetime.now(timezone.utc),
        )

        order.request_refund(amount=50.0, reason="Partial")

        assert order.refund_amount == 50.0

    def test_partial_refund_capped_at_remaining(self, test_domain):
        order = Order(
            status="delivered",
            total=100.0,
            partial_refund_amount=30.0,
            delivered_at=datetime.now(timezone.utc),
        )

        order.request_refund(amount=200.0, reason="Full")

        assert order.refund_amount == 70.0  # Capped at remaining
```

Five focused tests, each testing a specific business rule, without any
infrastructure setup. Fast, readable, and comprehensive.

---

## Event Handlers Follow the Same Pattern

Event handlers should be equally thin:

```python
# Thin event handler
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(
                order_id=event.order_id,
                quantity=item["quantity"],
            )
            repo.add(inventory)
```

The reservation logic (checking availability, preventing double-reservation,
updating quantities) lives in `Inventory.reserve()`, not in the handler.

---

## Application Services Follow the Same Pattern

Application services orchestrate use cases and should also be thin:

```python
@domain.application_service(part_of=Order)
class OrderApplicationService(BaseApplicationService):

    @use_case
    def place_order(self, order_id, customer_id, items, total, currency):
        repo = current_domain.repository_for(Order)
        order = Order(
            order_id=order_id,
            customer_id=customer_id,
            total=Money(amount=total, currency=currency),
        )
        for item in items:
            order.add_item(**item)
        order.place()
        repo.add(order)
```

Load or create, call domain methods, save. The application service coordinates
the sequence; the domain model contains the logic.

---

## When the Handler Has Extra Lines

Some legitimate additions to the three-line pattern:

### Loading Additional Data for Domain Services

```python
@handle(TransferMoney)
def transfer(self, command: TransferMoney):
    source = account_repo.get(command.from_account_id)
    policy = policy_repo.get(source.credit_policy_id)  # Extra load
    TransferService.validate_and_debit(source, policy, command.amount, ...)
    account_repo.add(source)
```

Loading a second aggregate for a domain service is fine -- the handler is
still just orchestrating.

### Creating New Aggregates

```python
@handle(PlaceOrder)
def place_order(self, command: PlaceOrder):
    order = Order(
        order_id=command.order_id,
        customer_id=command.customer_id,
    )
    for item in command.items:
        order.add_item(**item)  # Aggregate method
    order.place()               # Aggregate method
    repo.add(order)
```

Construction with multiple `add_item` calls is orchestration, not logic.

### Layer 4 Guards

```python
@handle(CancelOrder)
def cancel_order(self, command: CancelOrder):
    order = repo.get(command.order_id)

    # Contextual guard (Layer 4)
    if command.requested_by_role not in ("admin", "customer"):
        raise AuthorizationError("Unauthorized")

    order.cancel(command.reason)
    repo.add(order)
```

Authorization checks are the handler's responsibility (see
[Validation Layering](validation-layering.md)).

---

## Summary

| Aspect | Thick Handlers | Thin Handlers + Rich Domain |
|--------|---------------|----------------------------|
| Business logic | Scattered in handlers | Centralized in aggregates |
| Handler size | 20-50+ lines | 3-5 lines |
| Duplication | High (multiple handlers, same rules) | None (single aggregate method) |
| Testability | Requires infrastructure | Direct method calls |
| Aggregate role | Data container | Behavior + data |
| Domain service role | Unused | Cross-aggregate coordination |
| Code organization | Logic by handler | Logic by domain concept |
| Readability | Must read handler to understand rules | Method names express intent |

The principle: **handlers orchestrate. Aggregates think. Load, call, save.
If your handler knows business rules, the rules are in the wrong place.**
