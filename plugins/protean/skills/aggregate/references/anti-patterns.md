# Aggregate Anti-Patterns

Common mistakes when designing and implementing aggregates, with explanations and solutions.

## 1. Anemic Aggregates

**Problem:** Aggregates with only getters/setters and no behavior, violating the principle of encapsulation.

❌ **Bad:**

```python
@domain.aggregate
class Order:
    customer_id: String(required=True)
    status: String(default="draft")
    total: Float(default=0.0)

    # Just data, no behavior!

# Business logic scattered in services
def place_order(order_id: str):
    order = repository.get(order_id)
    order.status = "placed"  # Direct mutation
    order.total = calculate_total(order)
    repository.save(order)
```

✅ **Good:**

```python
@domain.aggregate
class Order:
    customer_id: String(required=True)
    status: String(default="draft")
    line_items = HasMany("LineItem")

    @property
    def total(self) -> float:
        """Calculated property."""
        return sum(item.subtotal for item in self.line_items)

    def place_order(self):
        """Business logic within aggregate."""
        if not self.line_items:
            raise ValueError("Cannot place empty order")
        self.status = "placed"

# Application service just orchestrates
def place_order(order_id: str):
    order = repository.get(order_id)
    order.place_order()  # Business logic in aggregate
    repository.save(order)
```

**Why it matters:**
- Encapsulation keeps related logic together
- Prevents business rules from being scattered
- Makes testing easier (test the aggregate, not services)
- Domain experts can understand aggregate methods

---

## 2. Aggregates That Are Too Large

**Problem:** An aggregate that holds too much. Two different things go wrong under that heading, and `check` only sees one of them.

- **Too many entity types.** `check` counts the entity classes in the cluster and reports `AGGREGATE_TOO_LARGE` once the count goes past `[lint] aggregate_size_limit` (default 5).
- **Too many rows behind a `HasMany`.** `check` reads the code, not the data, so it cannot see this one. You have to catch it while modelling.

The example below is the second kind. It declares three entity types, so it stays under the default limit and `check` says nothing, but every `Customer` load pulls the whole history back.

❌ **Bad:**

```python
@domain.aggregate
class Customer:
    name: String(required=True)
    orders = HasMany("Order")  # Could be thousands!
    support_tickets = HasMany("SupportTicket")  # Hundreds more
    interactions = HasMany("Interaction")  # Thousands more

    # This aggregate could have 10,000+ entities
```

✅ **Good:**

```python
# Customer aggregate - just core identity data
@domain.aggregate
class Customer:
    name: String(required=True)
    email: String(required=True)
    status: String(default="active")

# Order is its own aggregate
@domain.aggregate
class Order:
    customer_id: String(required=True)  # Reference, not containment
    status: String(default="draft")
    line_items = HasMany("LineItem")  # Limited items per order

# Support ticket is its own aggregate
@domain.aggregate
class SupportTicket:
    customer_id: String(required=True)  # Reference
    subject: String(required=True)
    status: String(default="open")
```

**Why it matters:**
- Aggregates load entire object graph eagerly
- Large graphs cause performance problems
- Violates transaction boundary principles
- Hard to reason about consistency

**Rule of thumb:**
- `check` flags an aggregate declaring more entity types than the configured `[lint] aggregate_size_limit` (default 5) as `AGGREGATE_TOO_LARGE`
- A clean `check` does not mean the aggregate is small. Judge row counts yourself
- If the aggregate is genuinely too large, split it into separate aggregates
- Reference by ID instead of containment

---

## 3. Direct Entity Access

**Problem:** Accessing or modifying entities outside of their aggregate root.

❌ **Bad:**

```python
# Trying to access entity directly
line_item_id = order.line_items[0].id
line_item = repository_for(LineItem).get(line_item_id)  # Wrong!
line_item.quantity = 5  # Wrong!
repository_for(LineItem).save(line_item)  # Wrong!
```

✅ **Good:**

```python
# Always work through aggregate
order = repository_for(Order).get(order_id)

# Modify through aggregate methods
for item in order.line_items:
    if item.product_id == "PROD-001":
        item.quantity = 5

# Save aggregate (entities are saved automatically)
repository_for(Order).save(order)
```

**Why it matters:**
- Entities are not independent - they're part of aggregate lifecycle
- Aggregate enforces invariants across all entities
- Transaction boundaries are at aggregate level
- Breaking this rule bypasses invariant checking

---

## 4. Missing Invariants

**Problem:** Not enforcing business rules, allowing invalid state.

❌ **Bad:**

```python
@domain.aggregate
class Account:
    balance: Float(default=0.0)
    overdraft_limit: Float(default=0.0)

    def withdraw(self, amount: float):
        self.balance -= amount  # No validation!

# Allows invalid state
account = Account(balance=100.0, overdraft_limit=50.0)
account.withdraw(200.0)  # balance = -100.0, violates overdraft!
```

✅ **Good:**

```python
@domain.aggregate
class Account:
    balance: Float(default=0.0)
    overdraft_limit: Float(default=0.0)

    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise InsufficientFundsException(
                "Balance cannot be below overdraft limit"
            )

    def withdraw(self, amount: float):
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self.balance -= amount
        # Invariant checked automatically
```

**Why it matters:**
- Aggregates exist to enforce business rules
- Without invariants, invalid data can be persisted
- Bugs are caught at aggregate boundary, not later in application

---

## 5. Violating Transaction Boundaries

**Problem:** Modifying multiple aggregates in a single transaction, coupling their lifecycles.

❌ **Bad:**

```python
def transfer_funds(from_account_id: str, to_account_id: str, amount: float):
    # Modifying two aggregates in one transaction!
    from_account = repository.get(from_account_id)
    to_account = repository.get(to_account_id)

    from_account.withdraw(amount)
    to_account.deposit(amount)

    # Both saved in same transaction
    repository.save(from_account)
    repository.save(to_account)
```

✅ **Good:**

```python
# Use eventual consistency with events
@domain.event(part_of="Account")
class FundsWithdrawn:
    account_id: String(required=True)
    amount: Float(required=True)
    transfer_id: String(required=True)

@domain.aggregate
class Account:
    def withdraw_for_transfer(self, amount: float, transfer_id: str):
        self.withdraw(amount)
        self.raise_(FundsWithdrawn(
            account_id=self.id,
            amount=amount,
            transfer_id=transfer_id
        ))

@domain.event_handler(part_of="Account")
class FundsWithdrawnHandler:
    @handle(FundsWithdrawn)
    def complete_transfer(self, event: FundsWithdrawn):
        # Handle in separate transaction
        to_account = repository.get(event.to_account_id)
        to_account.deposit(event.amount)
        repository.save(to_account)
```

**Why it matters:**
- Each aggregate is a transaction boundary
- Coupling transactions creates distributed transaction problems
- Eventual consistency is more scalable
- Domain events enable loose coupling

**Alternative:** Use a saga/process manager for complex multi-aggregate transactions.

---

## 6. Using Entities When Value Objects Are Better

**Problem:** Giving identity to concepts that should be value objects.

❌ **Bad:**

```python
@domain.entity(part_of="Order")
class Address:
    street: String(required=True)
    city: String(required=True)
    # Address has an ID but doesn't need one

@domain.aggregate
class Order:
    shipping_address = HasOne(Address)  # Overkill
```

✅ **Good:**

```python
@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    # No identity, immutable

@domain.aggregate
class Order:
    shipping_address = ValueObject(Address)  # Simpler
```

**Why it matters:**
- Value objects are simpler (no identity management)
- Immutability prevents accidental mutations
- Better performance (no separate database records)
- More intuitive model

**Rule:** If it's defined by its attributes (not identity), use a value object.

---

## 7. Exposing Collections Directly

**Problem:** Returning mutable collections that can be modified outside aggregate control.

❌ **Bad:**

```python
@domain.aggregate
class Order:
    _items = HasMany("OrderLine")

    @property
    def items(self):
        return self._items  # Direct access!

# Can violate invariants
order.items.append(LineItem(...))  # Bypasses add_items() method
```

✅ **Good:**

```python
@domain.aggregate
class Order:
    _items = HasMany("OrderLine")

    @property
    def items(self):
        return tuple(self._items)  # Immutable view

    def add_item(self, item: OrderLine):
        # Enforce invariants here
        if len(self._items) >= 50:
            raise ValueError("Cannot exceed 50 items")
        self._items.add(item)
```

**Note:** Protean's HasMany already handles this correctly with generated methods.

---

## 8. Aggregates Depending on Other Aggregates

**Problem:** Aggregate directly referencing or loading other aggregates.

❌ **Bad:**

```python
@domain.aggregate
class Order:
    customer_id: String(required=True)

    def validate_order(self):
        # Loading another aggregate!
        customer = repository_for(Customer).get(self.customer_id)
        if customer.credit_limit < self.total:
            raise ValueError("Exceeds credit limit")
```

✅ **Good:**

```python
# Use a domain service for cross-aggregate logic
@domain.domain_service
class OrderValidationService:
    def validate_order(self, order: Order, customer: Customer):
        if customer.credit_limit < order.total:
            raise ValueError("Exceeds credit limit")

# Or use events for eventual consistency
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True)
    customer_id: String(required=True)
    total: Float(required=True)

@domain.event_handler(part_of="Customer")
class OrderPlacedHandler:
    @handle(OrderPlaced)
    def check_credit_limit(self, event: OrderPlaced):
        customer = repository_for(Customer).get(event.customer_id)
        if customer.credit_limit < event.total:
            # Handle violation (cancel order, etc.)
            pass
```

**Why it matters:**
- Aggregates should be independent
- Cross-aggregate logic belongs in domain services
- Prevents coupling and circular dependencies
- Enables independent testing

---

## 9. Storing Calculated Values

**Problem:** Storing values that can be calculated from other data.

❌ **Bad:**

```python
@domain.aggregate
class Order:
    line_items = HasMany("OrderLine")
    total: Float(default=0.0)  # Stored!

    def add_item(self, item: OrderLine):
        self.add_line_items(item)
        # Must remember to update total everywhere!
        self.total = sum(item.subtotal for item in self.line_items)
```

✅ **Good:**

```python
@domain.aggregate
class Order:
    line_items = HasMany("OrderLine")

    @property
    def total(self) -> float:
        """Always calculated, never stored."""
        return sum(item.subtotal for item in self.line_items)
```

**Exception:** Storing calculated values is OK for:
- Performance optimization (with explicit recalculation)
- Historical snapshots (audit trail)
- Values that won't change (cached computation)

---

## 10. God Aggregates

**Problem:** One aggregate responsible for too many concepts.

❌ **Bad:**

```python
@domain.aggregate
class Customer:
    # Identity
    name: String(required=True)
    email: String(required=True)

    # Orders
    orders = HasMany("Order")

    # Billing
    credit_cards = HasMany("CreditCard")
    billing_address = ValueObject(Address)

    # Loyalty
    loyalty_points: Integer(default=0)
    tier: String(default="bronze")

    # Support
    tickets = HasMany("SupportTicket")

    # Too many responsibilities!
```

✅ **Good:**

```python
# Identity bounded context
@domain.aggregate
class Customer:
    name: String(required=True)
    email: String(required=True)
    status: String(default="active")

# Ordering bounded context
@domain.aggregate
class Order:
    customer_id: String(required=True)  # Reference

# Billing bounded context
@domain.aggregate
class BillingAccount:
    customer_id: String(required=True)  # Reference
    credit_cards = HasMany("CreditCard")

# Loyalty bounded context
@domain.aggregate
class LoyaltyAccount:
    customer_id: String(required=True)  # Reference
    points: Integer(default=0)
    tier: String(default="bronze")
```

**Why it matters:**
- Each aggregate should have one clear responsibility
- Separate bounded contexts for different business capabilities
- Enables independent scaling and deployment
- Reduces coupling

---

## Quick Reference: Aggregate Design Checklist

- [ ] Aggregate has behavior, not just data
- [ ] Aggregate stays within `[lint] aggregate_size_limit` (default 5 entity types), or raises the limit deliberately
- [ ] Entities accessed only through aggregate
- [ ] Business rules enforced via invariants
- [ ] Each aggregate is a transaction boundary
- [ ] Value objects used instead of entities where appropriate
- [ ] Collections not exposed for direct mutation
- [ ] No direct dependencies on other aggregates
- [ ] Calculated values use properties, not storage
- [ ] Aggregate has single, clear responsibility

## Related

- [Invariants](./invariants.md) - How to enforce business rules correctly
- [With Entities](./with-entities.md) - Proper entity usage
- [With Value Objects](./with-value-objects.md) - When to use value objects
- [domain-service](../../domain-service/SKILL.md) - Cross-aggregate logic
