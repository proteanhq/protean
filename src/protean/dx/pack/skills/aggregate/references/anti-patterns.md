# Aggregate Anti-Patterns

Common mistakes when designing and implementing aggregates, with explanations and solutions.

## 1. Anemic Aggregates

**Problem:** Aggregates with only getters/setters and no behavior, violating the principle of encapsulation.

❌ **Bad:**

```python
# fragment
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(default="draft")
    total: Decimal(precision=19, scale=4, default=0)

    # Just data, no behavior!

# Business logic scattered in services
def place_order(order_id: str):
    repository = current_domain.repository_for(Order)
    order = repository.get(order_id)
    order.status = "placed"  # Direct mutation
    order.total = calculate_total(order)
    repository.add(order)
```

✅ **Good:**

```python
from decimal import Decimal as D

from protean import current_domain


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(default="draft")
    line_items = HasMany("LineItem")

    @property
    def total(self) -> D:
        """Calculated property."""
        return sum((item.subtotal for item in self.line_items), D("0"))

    def place_order(self):
        """Business logic within aggregate."""
        if not self.line_items:
            raise ValueError("Cannot place empty order")
        self.status = "placed"


@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True)

    @property
    def subtotal(self) -> D:
        return self.quantity * self.unit_price


# Application service just orchestrates
def place_order(order_id: str):
    repository = current_domain.repository_for(Order)
    order = repository.get(order_id)
    order.place_order()  # Business logic in aggregate
    repository.add(order)
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
# fragment
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
    customer_id: Identifier(required=True)  # Held by id, not contained
    status: String(default="draft")
    line_items = HasMany("LineItem")  # Limited items per order

# Support ticket is its own aggregate
@domain.aggregate
class SupportTicket:
    customer_id: Identifier(required=True)  # Held by id
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
# fragment
# Trying to load and persist an entity on its own
line_item_id = order.line_items[0].id
line_items = current_domain.repository_for(LineItem)  # Wrong! Load the Order, not the entity
line_item = line_items.get(line_item_id)
line_item.quantity = 5  # Changed outside the aggregate, so its invariants never run
line_items.add(line_item)  # Wrong!
```

✅ **Good:**

```python
domain.init(traverse=False)

with domain.domain_context():
    repository = current_domain.repository_for(Order)

    order = Order(customer_id="C1")
    order.add_line_items(LineItem(product_id="PROD-001", quantity=1, unit_price="9.99"))
    repository.add(order)

    # Always work through the aggregate
    order = repository.get(order.id)

    # Modify entities through the aggregate
    for item in order.line_items:
        if item.product_id == "PROD-001":
            item.quantity = 5

    # Persist the aggregate (its entities are persisted with it)
    repository.add(order)
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
    balance: Decimal(precision=19, scale=4, default=0)
    overdraft_limit: Decimal(precision=19, scale=4, default=0)

    def withdraw(self, amount):
        self.balance -= amount  # No validation!

domain.init(traverse=False)

with domain.domain_context():
    # Allows invalid state
    account = Account(balance="100.00", overdraft_limit="50.00")
    account.withdraw(D("200.00"))  # balance = -100.00, violates overdraft!
```

✅ **Good:**

```python
from protean.exceptions import ValidationError

@domain.aggregate
class Account:
    balance: Decimal(precision=19, scale=4, default=0)
    overdraft_limit: Decimal(precision=19, scale=4, default=0)

    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise ValidationError(
                {"_entity": ["Balance cannot be below overdraft limit"]}
            )

    def withdraw(self, amount):
        if amount <= 0:
            raise ValueError("Amount must be positive")
        self.balance -= amount
        # Invariant checked automatically on the assignment
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
# fragment
def transfer_funds(from_account_id: str, to_account_id: str, amount):
    repository = current_domain.repository_for(Account)

    # Modifying two aggregates in one transaction!
    from_account = repository.get(from_account_id)
    to_account = repository.get(to_account_id)

    from_account.withdraw(amount)
    to_account.deposit(amount)

    # Both persisted in the same unit of work
    repository.add(from_account)
    repository.add(to_account)
```

✅ **Good:**

```python
# Use eventual consistency with events
@domain.event(part_of="Account")
class FundsWithdrawn:
    account_id: Identifier(required=True)
    to_account_id: Identifier(required=True)
    amount: Decimal(precision=19, scale=4, required=True)
    transfer_id: Identifier(required=True)

@domain.aggregate
class Account:
    balance: Decimal(precision=19, scale=4, default=0)

    def withdraw(self, amount):
        self.balance -= amount

    def deposit(self, amount):
        self.balance += amount

    def withdraw_for_transfer(self, amount, to_account_id: str, transfer_id: str):
        self.withdraw(amount)
        self.raise_(FundsWithdrawn(
            account_id=self.id,
            to_account_id=to_account_id,
            amount=amount,
            transfer_id=transfer_id
        ))

@domain.event_handler(part_of="Account")
class FundsWithdrawnHandler:
    @handle(FundsWithdrawn)
    def complete_transfer(self, event: FundsWithdrawn):
        # Runs in its own transaction, after the withdrawal is committed
        repository = current_domain.repository_for(Account)
        to_account = repository.get(event.to_account_id)
        to_account.deposit(event.amount)
        repository.add(to_account)
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
# fragment
# Appending to the list skips the invariant checks,
# and the repository does not persist the appended item
order.line_items.append(OrderLine(sku="SKU-1"))
```

✅ **Good:**

```python
@domain.aggregate
class Order:
    line_items = HasMany("OrderLine")

    @invariant.post
    def cannot_exceed_50_items(self):
        if len(self.line_items) > 50:
            raise ValidationError({"line_items": ["Cannot exceed 50 items"]})


@domain.entity(part_of="Order")
class OrderLine:
    sku: String(required=True)
    quantity: Integer(default=1, min_value=1)
    unit_price: Decimal(precision=19, scale=4, default=0)

    @property
    def subtotal(self) -> D:
        return self.quantity * self.unit_price


domain.init(traverse=False)

with domain.domain_context():
    order = Order()
    order.add_line_items(OrderLine(sku="SKU-1"))  # Checks invariants, tracked for persistence
```

`HasMany` generates `add_line_items()`, `remove_line_items()`, `get_one_from_line_items()` and `filter_line_items()`. Change the collection only through these helpers, or through aggregate methods that call them.

---

## 8. Aggregates Depending on Other Aggregates

**Problem:** Aggregate directly referencing or loading other aggregates.

❌ **Bad:**

```python
# fragment
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)

    def validate_order(self):
        # Loading another aggregate!
        customer = current_domain.repository_for(Customer).get(self.customer_id)
        if customer.credit_limit < self.total:
            raise ValueError("Exceeds credit limit")
```

✅ **Good:**

```python
@domain.aggregate
class Customer:
    name: String(required=True)
    credit_limit: Decimal(precision=19, scale=4, default=0)


# Use a domain service for logic that spans two aggregates
@domain.domain_service(part_of=[Order, Customer])
class OrderCreditCheck:
    def __init__(self, order, customer):
        super().__init__(order, customer)
        self.order = order
        self.customer = customer

    def check(self):
        order_total = sum((item.subtotal for item in self.order.line_items), D("0"))
        if order_total > self.customer.credit_limit:
            raise ValidationError({"_entity": ["Order exceeds the credit limit"]})
```

The caller (a command handler or application service) loads both aggregates through their repositories, runs the service, and persists the result.

When the second step can happen later, in its own transaction, use an event instead. `Order` raises `OrderPlaced`. An event handler in `Order`'s own cluster reacts and issues a command, and the other aggregate's command handler does the work. The [split-aggregate](../../split-aggregate/SKILL.md) skill shows this form. It also covers why the handler stays in the cluster that owns the event, and how to make the step safe to repeat.

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
    total: Decimal(precision=19, scale=4, default=0)  # Stored!

    def add_item(self, item: OrderLine):
        self.add_line_items(item)
        # Must remember to update total everywhere!
        self.total = sum((item.subtotal for item in self.line_items), D("0"))
```

✅ **Good:**

```python
@domain.aggregate
class Order:
    line_items = HasMany("OrderLine")

    @property
    def total(self) -> D:
        """Always calculated, never stored."""
        return sum((item.subtotal for item in self.line_items), D("0"))
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
# fragment
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
    customer_id: Identifier(required=True)  # Held by id

# Billing bounded context
@domain.aggregate
class BillingAccount:
    customer_id: Identifier(required=True)  # Held by id
    credit_cards = HasMany("CreditCard")

@domain.entity(part_of="BillingAccount")
class CreditCard:
    last_four: String(max_length=4)

# Loyalty bounded context
@domain.aggregate
class LoyaltyAccount:
    customer_id: Identifier(required=True)  # Held by id
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
