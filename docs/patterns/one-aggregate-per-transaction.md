# One Aggregate Per Transaction

## The Problem

A command handler receives a `TransferMoney` command. It loads the source
account, debits it, loads the target account, credits it, and persists both
in the same transaction. The code looks clean and the test passes. Then it
reaches production.

Two transfers involving the same account execute concurrently. Both load the
account at version 5. Both try to write version 6. One succeeds, the other
fails with a concurrency conflict. The user retries, and now the system must
untangle which transfer succeeded, which failed, and whether any money was
lost.

This is the cost of modifying multiple aggregates in a single transaction.

The problems compound:

- **Deadlocks.** Two transactions each hold a lock on one aggregate and wait for
  a lock on the other. Database deadlock detection kills one transaction, but the
  retry may deadlock again.

- **Increased failure surface.** A transaction that touches two aggregates can
  fail because of a conflict on *either* one. The probability of failure
  increases multiplicatively, not additively, with each aggregate added to the
  transaction.

- **Coupling through transactions.** If Account and Inventory are modified in
  the same transaction, they cannot be stored in different databases, cannot be
  scaled independently, and cannot be deployed independently. The transaction
  boundary is a hard architectural constraint.

- **Unclear rollback semantics.** If the credit succeeds but the debit fails,
  what happens? The transaction rolls back both -- but what if the credit had
  already raised a domain event that was partially processed? Partial failures
  in multi-aggregate transactions are difficult to reason about and harder to
  recover from.

- **Violated aggregate boundaries.** DDD defines an aggregate as the unit of
  consistency -- the boundary within which invariants are guaranteed. Modifying
  two aggregates in one transaction blurs those boundaries. You're no longer
  treating aggregates as independent consistency units; you're treating the
  transaction as the consistency unit, which defeats the purpose of aggregate
  design.

The root cause: **the transaction boundary does not match the aggregate
boundary**.

---

## The Pattern

Modify **exactly one aggregate per transaction**. Cross-aggregate side effects
flow through **domain events**, processed in their own separate transactions.

```
Anti-pattern:
  Transaction {
    Load Aggregate A → Mutate A
    Load Aggregate B → Mutate B
    Persist A + B together
  }

Pattern:
  Transaction 1 {
    Load Aggregate A → Mutate A → Raise Event → Persist A
  }
  ──── Event ────►
  Transaction 2 {
    Load Aggregate B → Mutate B → Persist B
  }
```

Each aggregate is loaded, modified, and persisted in its own transaction. The
link between them is a domain event -- an asynchronous, reliable message that
triggers the next step.

This means cross-aggregate changes are **eventually consistent** rather than
immediately consistent. The business must accept that there is a brief window
between the first aggregate's change and the second aggregate's reaction. In
practice, this window is milliseconds to seconds, and the business almost always
tolerates it.

---

## Why This Matters

### Aggregates Are Consistency Boundaries

This is definitional. In Eric Evans' original formulation, an aggregate is:

> A cluster of associated objects that are treated as a unit for the purpose of
> data changes. External references are restricted to one member of the
> Aggregate, designated as the root. A set of consistency rules applies within
> the Aggregate's boundaries.

The aggregate *is* the transaction boundary. Modifying multiple aggregates in
one transaction expands the transaction boundary beyond the aggregate, which
contradicts the aggregate's purpose.

### Eventual Consistency Is Usually Sufficient

Most cross-aggregate operations don't require immediate consistency. Consider:

- "When an order is placed, reserve inventory." -- Does the inventory need to
  be reserved in the same instant the order is placed? No. Milliseconds later
  is fine. If reservation fails, a compensating action cancels the order.

- "When a user upgrades their plan, update their feature flags." -- Does the
  flag update need to be atomic with the plan change? No. A few seconds of
  delay is invisible to the user.

- "When a payment is confirmed, mark the order as paid." -- The payment system
  is already asynchronous. Adding a brief delay for the order update is
  negligible.

The business operations that truly require multi-aggregate atomicity are rare.
When they arise, consider whether the aggregate boundaries are drawn correctly
-- perhaps those two "aggregates" should actually be one.

### Independent Scalability

When each aggregate is its own transaction, aggregates can be:
- Stored in different databases or tables
- Sharded independently
- Processed by different services
- Deployed on different schedules

This flexibility is impossible when transactions span multiple aggregates.

---

## How Protean Supports This

Protean's architecture naturally guides you toward one-aggregate-per-transaction,
though it doesn't enforce it.

### Unit of Work

Protean's Unit of Work (UoW) manages the transaction for a single operation.
When a command handler or application service runs inside a UoW, all changes
to aggregates within that UoW are persisted atomically.

The intended usage: one aggregate per UoW.

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # The @handle decorator wraps this method in a UoW
        repo = current_domain.repository_for(Order)
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            items=command.items,
        )
        order.place()  # Mutates and raises OrderPlaced event
        repo.add(order)
        # UoW commits: Order is persisted, OrderPlaced event is published
```

The UoW commits the Order and publishes its events in a single atomic
operation. The events are then processed in their own separate UoW contexts.

### Domain Events

Events are the mechanism for cross-aggregate communication. When an aggregate
raises an event, Protean stores it and delivers it to registered handlers:

```python
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)


@domain.aggregate
class Order:
    # ... fields ...

    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            items=[item.to_dict() for item in self.items],
            total=self.total,
        ))
```

The event carries all the data the downstream handler needs. The handler runs
in its own transaction:

```python
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # This runs in its own UoW -- separate transaction
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(item["quantity"])
            repo.add(inventory)
```

### Event Handlers Run Independently

Each event handler invocation runs in its own UoW context. If the inventory
reservation fails, the Order is already placed -- the failure is isolated.
The event handler can retry, and if it ultimately fails, the system can raise
a compensating event or alert for manual intervention.

This is the natural architecture: aggregates are modified one at a time, events
carry information between them, and failures are contained.

---

## Applying the Pattern

### The Money Transfer Example

The classic example of a multi-aggregate operation: transferring money between
two accounts.

**Anti-pattern: both accounts in one transaction**

```python
# Anti-pattern: modifying two aggregates
@handle(TransferMoney)
def transfer(self, command: TransferMoney):
    repo = current_domain.repository_for(Account)

    source = repo.get(command.from_account_id)
    source.debit(command.amount)
    repo.add(source)

    # WRONG: this modifies a second aggregate in the same transaction
    target = repo.get(command.to_account_id)
    target.credit(command.amount)
    repo.add(target)
```

**Pattern: debit first, event triggers credit**

```python
@domain.event(part_of=Account)
class MoneyDebited(BaseEvent):
    account_id: Identifier(required=True)
    amount: Float(required=True)
    transfer_id: Identifier(required=True)
    target_account_id: Identifier(required=True)


@domain.aggregate
class Account:
    account_id: Auto(identifier=True)
    balance: Float(default=0.0)
    overdraft_limit: Float(default=0.0)

    def debit(self, amount, transfer_id, target_account_id):
        if self.balance - amount < -self.overdraft_limit:
            raise ValidationError(
                {"balance": ["Insufficient funds for transfer"]}
            )
        self.balance -= amount
        self.raise_(MoneyDebited(
            account_id=self.account_id,
            amount=amount,
            transfer_id=transfer_id,
            target_account_id=target_account_id,
        ))

    def credit(self, amount):
        self.balance += amount


@domain.command_handler(part_of=Account)
class AccountCommandHandler(BaseCommandHandler):

    @handle(TransferMoney)
    def transfer(self, command: TransferMoney):
        repo = current_domain.repository_for(Account)
        source = repo.get(command.from_account_id)
        source.debit(
            command.amount,
            transfer_id=command.transfer_id,
            target_account_id=command.to_account_id,
        )
        repo.add(source)
        # Only the source account is modified here.
        # The MoneyDebited event will trigger the credit.


@domain.event_handler(part_of=Account)
class AccountEventHandler(BaseEventHandler):

    @handle(MoneyDebited)
    def on_money_debited(self, event: MoneyDebited):
        repo = current_domain.repository_for(Account)
        target = repo.get(event.target_account_id)
        target.credit(event.amount)
        repo.add(target)
```

**What about failure?** If the credit fails (target account doesn't exist,
database error), the debit has already been committed. The event handler retries.
If retries are exhausted, a compensating action re-credits the source account.
This is the saga pattern -- complex, but each step is a single-aggregate
transaction, making failures predictable and recoverable.

### Order Fulfillment Pipeline

A more realistic example with multiple downstream aggregates:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        repo = current_domain.repository_for(Order)
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            items=command.items,
        )
        order.place()
        repo.add(order)
        # OrderPlaced event is raised by order.place()


# Each downstream concern handles the event independently
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(item["quantity"])
            repo.add(inventory)


@domain.event_handler(part_of=CustomerLoyalty)
class LoyaltyEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def award_points(self, event: OrderPlaced):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(event.customer_id)
        loyalty.add_points(int(event.total))
        repo.add(loyalty)


@domain.event_handler(part_of=Notification)
class NotificationEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def send_confirmation(self, event: OrderPlaced):
        repo = current_domain.repository_for(Notification)
        notification = Notification(
            recipient_id=event.customer_id,
            template="order_confirmation",
            data={"order_id": event.order_id, "total": event.total},
        )
        repo.add(notification)
```

One command, one aggregate mutation, one transaction. Three downstream
handlers, each modifying their own aggregate in their own transaction. If
the notification fails, the order is still placed and inventory is still
reserved. Each concern is independent.

---

## Domain Services: The Exception That Isn't

Domain services coordinate logic that spans multiple aggregates -- but they
should **read** from multiple aggregates, not **write** to them.

A domain service can validate a business rule that requires data from multiple
aggregates, and then the command handler modifies only one:

```python
@domain.domain_service(part_of=[Account, CreditPolicy])
class TransferEligibilityService:
    """Validates whether a transfer is allowed based on account state
    and credit policies. Does NOT modify any aggregates."""

    @classmethod
    def validate_transfer(cls, source_account, credit_policy, amount):
        if source_account.is_frozen:
            raise ValidationError(
                {"account": ["Source account is frozen"]}
            )

        if amount > credit_policy.max_transfer_amount:
            raise ValidationError(
                {"amount": [
                    f"Transfer exceeds maximum of "
                    f"{credit_policy.max_transfer_amount}"
                ]}
            )

        if source_account.balance - amount < -source_account.overdraft_limit:
            raise ValidationError(
                {"balance": ["Insufficient funds"]}
            )


@domain.command_handler(part_of=Account)
class AccountCommandHandler(BaseCommandHandler):

    @handle(TransferMoney)
    def transfer(self, command: TransferMoney):
        repo = current_domain.repository_for(Account)
        source = repo.get(command.from_account_id)

        policy_repo = current_domain.repository_for(CreditPolicy)
        policy = policy_repo.get(source.credit_policy_id)

        # Domain service validates using both aggregates
        TransferEligibilityService.validate_transfer(
            source, policy, command.amount,
        )

        # But only the source account is modified
        source.debit(
            command.amount,
            transfer_id=command.transfer_id,
            target_account_id=command.to_account_id,
        )
        repo.add(source)
```

The domain service reads from `Account` and `CreditPolicy` but modifies
neither. The command handler modifies only `Account`. The pattern holds.

---

## When to Bend the Rule

### True Business Atomicity Requirements

Occasionally, the business genuinely requires two things to change atomically.
If you encounter this, first question whether the aggregate boundaries are
correct. Often, the data that must be consistent together belongs in the same
aggregate.

If after analysis you're certain the data belongs in separate aggregates but
must be atomically consistent, you have a modeling tension. Options:

1. **Merge the aggregates.** If they must always change together, they may not
   be truly separate aggregates.
2. **Accept eventual consistency with compensating actions.** Most "must be
   atomic" requirements soften when you discuss the actual business impact of
   a brief inconsistency window.
3. **Use database-level transactions as a conscious trade-off.** This sacrifices
   independent scalability for immediate consistency. Document it as technical
   debt.

### Bulk Operations

Some operations naturally batch changes to many instances of the same aggregate
type (e.g., closing all orders past a deadline). These are still
one-aggregate-per-transaction if each instance is processed in its own UoW. The
command handler iterates, but each iteration is a separate transaction:

```python
@handle(CloseExpiredOrders)
def close_expired(self, command: CloseExpiredOrders):
    repo = current_domain.repository_for(Order)
    expired_orders = repo.query(Order.status == "pending", Order.deadline < now())

    for order in expired_orders:
        # Each order is processed in its own conceptual transaction
        order.close("Expired past deadline")
        repo.add(order)
```

---

## Signs You're Violating the Pattern

1. **Your handler calls `repo.add()` for more than one aggregate type.**
   Each `repo.add()` is a persistence operation. Multiple adds for different
   aggregate types means multiple aggregates are being modified.

2. **Your handler calls `repo.get()` for a second aggregate and then mutates
   it.** Reading another aggregate for validation is fine. Mutating it is not.

3. **Your tests need to verify state changes in two aggregates after a single
   command.** This suggests the command is doing too much.

4. **Concurrent operations on different aggregates cause unexpected conflicts.**
   If updating a Customer's address causes a concurrency conflict on their
   Order, the transaction scope is too wide.

5. **You're using database-level locks or `SELECT FOR UPDATE` across tables.**
   This is a symptom of multi-aggregate transactions forcing coordination at the
   database level.

---

## Summary

| Aspect | Multi-Aggregate Transaction | One Aggregate Per Transaction |
|--------|----------------------------|------------------------------|
| Consistency | Immediate | Eventual (via events) |
| Failure handling | All-or-nothing rollback | Per-aggregate, with compensation |
| Contention | High (locks span aggregates) | Low (locks are per-aggregate) |
| Scalability | Limited (coupled storage) | Independent (per aggregate) |
| Complexity | Simple code, complex failure modes | Slightly more code, simple failure modes |
| Testing | Must set up multiple aggregates | Test each aggregate independently |
| Protean support | Possible but not recommended | Natural fit with UoW + events |

The principle: **one aggregate, one transaction, one commit. Everything else
flows through events.**
