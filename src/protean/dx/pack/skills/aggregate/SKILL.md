---
name: aggregate
description: Define a Protean aggregate - the root entity of a cluster of domain objects treated as a single unit for data changes. Aggregates are fundamental building blocks that encapsulate business logic, enforce invariants, and define transaction boundaries. Use when creating domain entities with identity that change over time, when modeling business concepts that need to enforce consistency rules, when the user asks to "create an aggregate", "add a domain model", "define a root entity", or when they describe a core business concept that needs to persist state and enforce rules (like Order, Customer, Account, Product). Aggregates can contain entities and value objects, and are responsible for maintaining business invariants across their object graph.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - AGGREGATE_NOT_NOUN
    - AGGREGATE_NO_INVARIANTS
    - AGGREGATE_TOO_LARGE
    - AGGREGATE_WITHOUT_COMMAND_HANDLER
    - CROSS_AGGREGATE_REFERENCE
---

# Aggregate

## Basic structure

An aggregate is defined using the `@domain.aggregate` decorator:

```python
from protean import Domain
from protean.fields import String, Date, Integer

domain = Domain()

@domain.aggregate
class Post:
    title: String(required=True, max_length=200)
    content: String(max_length=5000)
    status: String(max_length=20, default="draft")
    published_on: Date()
    view_count: Integer(default=0)
```

## Key rules

1. **Aggregates are the root of an object graph** - They manage entities and value objects within their boundary
2. **Aggregates enforce business invariants** - Use `@invariant.pre` and `@invariant.post` decorators. **All business validations should be codified as granular invariants** - one rule per invariant
3. **Aggregates are transaction boundaries** - All changes within an aggregate are saved together
4. **Aggregates have automatic identity** - An `id` field is auto-generated unless `auto_add_id_field=False`
5. **Aggregates are versioned** - Every aggregate has a `_version` field for optimistic concurrency control
6. **Keep aggregates small** - `check` flags an aggregate with more entity types than the configured `aggregate_size_limit` (default 5) as `AGGREGATE_TOO_LARGE`. Split a growing aggregate, or raise the limit if the size is intentional
7. **Entities accessed only through aggregates** - Never reference entities directly from outside
8. **Each aggregate is independent** - Don't load other aggregates within aggregate methods

## Fields and associations

### Simple Fields with built-in validations

**Important**: Protean fields come with built-in validation parameters. Always use these instead of manual validation in methods.

```python
from protean.fields import String, Integer, Float, Boolean, Date, DateTime, Text

@domain.aggregate
class Product:
    name: String(required=True, max_length=200, min_length=3)
    description: Text()
    price: Float(required=True, min_value=0.01)  # Field-level validation
    in_stock: Boolean(default=True)
    stock_count: Integer(default=0, min_value=0)  # Field-level validation
    discount_percent: Float(min_value=0.0, max_value=100.0, default=0.0)
    created_at: DateTime(default=utc_now)
```

**Common field validation parameters**:
- **All fields**: `required`, `default`, `unique`, `choices`, `validators`
- **String/Text**: `max_length`, `min_length`, `sanitize`
- **Integer/Float**: `min_value`, `max_value`

**Use field validations for**:
- Data type constraints (string length, number ranges)
- Required/optional status
- Uniqueness constraints
- Default values

**Use invariants for**:
- Cross-field business rules (e.g., "end_date must be after start_date")
- Complex domain logic involving multiple attributes
- State-dependent validations

### HasOne Association

One-to-one relationship with an entity:

```python
from protean.fields import HasOne

@domain.aggregate
class Order:
    customer_id: String(required=True)
    shipping_info = HasOne("ShippingInfo")

@domain.entity(part_of="Order")
class ShippingInfo:
    address: String(required=True, max_length=500)
    city: String(required=True, max_length=100)
```

**Note**: For `HasOne` relationships, access the related entity directly through the field (e.g., `order.shipping_info`). No special helper methods are needed.

### HasMany Association

One-to-many relationship with entities:

```python
from protean.fields import HasMany

@domain.aggregate
class Order:
    customer_id: String(required=True)
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)
    unit_price: Float(required=True)
```

**Auto-generated helper methods**: When you define a `HasMany` field, Protean automatically creates helper methods for managing the association. For the `line_items` field above, these methods are generated:

- `add_line_items(item)` - Add one or more items to the collection
- `remove_line_items(item)` - Remove an item from the collection
- `get_one_from_line_items(identifier)` - Get a specific item by its identifier
- `filter_line_items(**criteria)` - Filter items based on criteria

**Important**: Do NOT manually create these methods - they are automatically available. Only create custom methods if you need behavior different from the defaults (e.g., custom validation when adding items).

### ValueObject Field

For complex immutable data types:

```python
from protean.fields import ValueObject

@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.aggregate
class Order:
    customer_id: String(required=True)
    total = ValueObject(Money)
```

## Initialization

Create aggregate instances by passing field values as keyword arguments:

```python
# Simple aggregate
post = Post(
    title="Getting Started with Protean",
    content="Protean is a DDD framework...",
    status="draft"
)

# With entities (using auto-generated add_line_items() helper)
order = Order(customer_id="C123")
order.add_line_items(LineItem(product_id="P1", quantity=2, unit_price=50.0))

# With value objects
order = Order(
    customer_id="C123",
    total=Money(amount=100.0, currency="USD")
)
```

The `id` field is automatically generated on creation.

## State mutations

Define methods on the aggregate to change state:

```python
@domain.aggregate
class Order:
    status: String(max_length=20, default="draft")
    line_items = HasMany("LineItem")

    def add_item(self, product_id: str, quantity: int, price: float):
        """Add an item to the order with custom business logic.

        Note: This uses the auto-generated add_line_items() helper.
        Create custom methods like this when you need additional validation,
        calculations, or business logic beyond simple item addition.
        """
        item = LineItem(product_id=product_id, quantity=quantity, unit_price=price)
        self.add_line_items(item)  # Uses auto-generated helper

    def place_order(self):
        """Place the order."""
        if not self.line_items:
            raise ValueError("Cannot place empty order")
        self.status = "placed"

    def cancel(self):
        """Cancel the order."""
        if self.status == "shipped":
            raise ValueError("Cannot cancel shipped order")
        self.status = "cancelled"
```

## Invariants (business rules)

**Important principle**: All business validations should be codified as invariants, as granularly as possible. Each invariant should check a single business rule. Protean automatically enforces invariants after initialization and whenever attributes change.

Use `@invariant.pre` (checked before changes) and `@invariant.post` (checked after changes):

- **`@invariant.post`**: Validates after changes occur. Use for constraints that depend on the final state (e.g., "balance must not be negative"). Checked after initialization and after attribute updates.
- **`@invariant.pre`**: Validates before changes occur. Use for preconditions that must be true before allowing state changes (e.g., "account must be active"). **Note**: Pre invariants are NOT checked during initialization.

```python
from protean import invariant

class InsufficientFundsException(Exception):
    pass

@domain.aggregate
class Account:
    balance: Float(default=0.0)
    overdraft_limit: Float(default=0.0)
    status: String(default="active")

    # Post invariants - checked after initialization and after changes
    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        """Balance cannot fall below the negative overdraft limit.

        Granular rule: Each invariant checks ONE business constraint.
        """
        if self.balance < -self.overdraft_limit:
            raise InsufficientFundsException(
                f"Balance cannot be below overdraft limit"
            )

    # Pre invariants - only checked before changes (NOT during initialization)
    @invariant.pre
    def account_must_be_active(self):
        """Account must be active for transactions.

        Pre-check ensures we don't attempt invalid operations.
        """
        if self.status != "active":
            raise ValueError("Account is not active")

    def withdraw(self, amount: float):
        """Withdraw money from account.

        Note: Parameter validations (amount > 0) belong in the method
        when they validate method arguments, not aggregate fields.
        Field-level constraints should be defined on the field itself.
        """
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        self.balance -= amount  # Invariants automatically checked after this
```

**Best practices**:
1. **One rule per invariant** - Keep invariants granular and focused
2. **Use descriptive names** - Name should clearly describe the rule being enforced
3. **Prefer `@invariant.post`** - Use for most validations that check final state
4. **Use `@invariant.pre` sparingly** - Only for preconditions that must prevent state changes
5. **Document the rule** - Add docstrings explaining the business constraint

## Inheritance

Create abstract base aggregates for shared fields:

```python
from datetime import datetime, timezone

def utc_now():
    return datetime.now(timezone.utc)

@domain.aggregate(abstract=True)
class TimeStamped:
    """Abstract base with timestamp fields."""
    created_at: DateTime(default=utc_now)
    updated_at: DateTime(default=utc_now)

@domain.aggregate
class User(TimeStamped):
    """Concrete aggregate inheriting timestamps."""
    email: String(required=True, max_length=255)
    name: String(required=True, max_length=200)
```

## Configuration options

Pass options to the decorator:

```python
@domain.aggregate(
    abstract=True,              # Cannot be instantiated
    auto_add_id_field=False,    # Control automatic ID field
    provider="orders_db",       # Database to use
    schema_name="customer_orders",  # Table/collection name
    stream_category="order"     # Event sourcing stream category
)
class Order:
    ...
```

See [Configuration Reference](references/configuration.md) for detailed documentation.

## Persistence

Aggregates are persisted using repositories:

```python
from protean.globals import current_domain

# Create
order = Order(customer_id="C123")
order.add_line_items(LineItem(...))  # Auto-generated helper
current_domain.repository_for(Order).add(order)

# Retrieve
order = current_domain.repository_for(Order).get(order_id)

# Update
order.status = "placed"
current_domain.repository_for(Order).add(order)

# Delete
current_domain.repository_for(Order).remove(order)
```

## Quick example

```python
from protean import Domain, invariant
from protean.fields import String, Float, HasMany, Integer

domain = Domain()

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True, max_length=50)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True)

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price

@domain.aggregate
class Order:
    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="draft")
    line_items = HasMany(LineItem)

    @property
    def total(self) -> float:
        return sum(item.subtotal for item in self.line_items)

    @invariant.post
    def placed_order_must_have_items(self):
        if self.status == "placed" and not self.line_items:
            raise ValueError("Cannot place empty order")

    def place_order(self):
        if not self.line_items:
            raise ValueError("Cannot place empty order")
        self.status = "placed"

# Usage
order = Order(customer_id="CUST-12345")
# Using auto-generated add_line_items() helper
order.add_line_items(LineItem(product_id="PROD-001", quantity=2, unit_price=29.99))
order.add_line_items(LineItem(product_id="PROD-002", quantity=1, unit_price=49.99))
order.place_order()

print(f"Order total: ${order.total:.2f}")
print(f"Status: {order.status}")
```

## Common mistakes

### ❌ Anemic aggregates (only data, no behavior)

```python
@domain.aggregate
class Order:
    status: String(default="draft")
    # No methods! Business logic scattered elsewhere
```

✅ **Instead**: Encapsulate behavior in aggregate methods.

### ❌ Missing invariants (using method-level validations instead)

```python
def withdraw(self, amount):
    if self.balance - amount < 0:  # Bad: duplicated across methods
        raise ValueError("Insufficient funds")
```

✅ **Instead**: Codify ALL business rules as granular `@invariant.post` — automatically enforced everywhere.

### ❌ Not using field-level validations

```python
price: Float(required=True)  # No min_value!
def set_price(self, p):
    if p <= 0: raise ValueError(...)  # Manual validation
```

✅ **Instead**: `price: Float(required=True, min_value=0.01)` — field handles it.

See [Anti-patterns](references/anti-patterns.md) for additional mistakes: oversized aggregates, direct entity access, transaction boundary violations, manually recreating auto-generated helpers.

### What `check` reports

`check` inspects your aggregates and reports these diagnostics:

- `AGGREGATE_NO_INVARIANTS`: the aggregate declares no `@invariant.pre` or `@invariant.post` method, so it enforces no business rules and is usually an anemic data holder. Add the invariants it must always satisfy, or reconsider whether this concept is an aggregate.
- `AGGREGATE_NOT_NOUN`: the aggregate's name ends in a suffix that reads as a verb, gerund, or adjective (`OrderProcessing`, `Cancelable`). Rename it to the domain-concept noun it models (`Order`).
- `AGGREGATE_TOO_LARGE`: the aggregate declares more entity types than the configured `[lint] aggregate_size_limit`. The count is of entity classes in the cluster, not of rows loaded at runtime. Split it into smaller aggregates, or raise the limit if the size is intentional.
- `AGGREGATE_WITHOUT_COMMAND_HANDLER`: the aggregate has no command handler, so nothing can change its state. Add a command handler for it, or model it as a read-only projection if no writes are expected.
- `CROSS_AGGREGATE_REFERENCE`: a field holds a direct `Reference` to another aggregate root. Hold the other aggregate by its identifier instead (`<other>_id: Identifier()`) and load it through its own repository when needed.

## Detailed references

### Core Concepts
- [Aggregates with Entities](references/with-entities.md) - HasOne and HasMany relationships
- [Aggregates with Value Objects](references/with-value-objects.md) - Using value objects for complex data
- [Invariants](references/invariants.md) - Enforcing business rules with pre/post conditions
- [Configuration Options](references/configuration.md) - Complete reference for all options
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Simple Aggregate](assets/aggregate_simple.py) - Basic aggregate with fields
- [Aggregate with Entities](assets/aggregate_with_entity.py) - HasOne and HasMany relationships
- [Aggregate with Value Objects](assets/aggregate_with_value_object.py) - Money, Address examples
- [Aggregate with Invariants](assets/aggregate_with_invariants.py) - Business rule enforcement
- [Aggregate Inheritance](assets/aggregate_inheritance.py) - Abstract bases and inheritance

### Related Skills
- `entity` - Entities within aggregates
- `value-object` - Value objects for complex data
- `command` - Commands that trigger aggregate state changes
- `event` - Events raised by aggregates
- `repository` - Persisting and retrieving aggregates
- `event-sourced-aggregate` - Event-sourced aggregates with @apply, from_events(), fact events

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
