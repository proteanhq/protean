---
name: value-object
description: Define a Protean value object - an immutable domain element without identity, defined by its attributes. Value objects represent descriptive concepts like Money, Email, Address, or Coordinates. Use when modeling concepts where identity doesn't matter, only the values do. Use when the user asks to "create a value object", "add a VO", "model money/email/address", or describes something that measures or describes (amounts, locations, contact info). Value objects are always embedded in aggregates or entities, never exist independently, and two instances with the same attributes are considered equal.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - VALUE_OBJECT_MUTABLE_FIELD
    - VALUE_OBJECT_INVARIANT_FAILED
---

# Value Object

Value objects are immutable domain elements that represent descriptive concepts without identity. They are defined entirely by their attribute values - two value objects with the same attributes are considered equal, regardless of instance.

## Important context: Value vs Entity decision

A critical question: does this concept need identity?

**Example: Currency note**
- In most domains: Value Object (a $10 bill is a $10 bill)
- For a federal bank printing money: Entity (specific note with serial number matters)

**Key questions:**
- Does identity matter more than attributes?
- Can two instances with same attributes be swapped?
- Should it be immutable?

If identity matters → Use Entity or Aggregate instead.
If values matter → Use Value Object.

See [Deciding Between Elements](https://docs.proteanhq.com/guides/domain-definition/deciding-between-elements/) for comprehensive guidance.

## Basic structure

A value object is defined using the `@domain.value_object` decorator:

```python
from protean import Domain
from protean.fields import String, Float

domain = Domain(__name__)

@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True, min_value=0.0)
```

## Key rules

1. **Value objects are immutable** - Cannot be changed once created
2. **Value objects have no identity** - Cannot use `identifier=True` or `unique=True`
3. **Equality is by attributes** - Two VOs with same values are equal
4. **Value objects are embedded** - Always part of aggregates or entities
5. **Value objects are self-contained** - Should not reference entities
6. **Replace, don't modify** - Create new instance to "change" a value object
7. **Can contain other value objects** - Nesting is allowed and encouraged
8. **Should encapsulate validation** - **All business validations should be codified as granular invariants** using `@invariant.post` (one rule per invariant)

## Defining value objects

### Simple value object

**Important**: Always use field-level validation parameters for data type constraints.

```python
@domain.value_object
class Balance:
    """Currency and amount with field-level validations."""
    currency: String(max_length=3, min_length=3, required=True)  # ISO code
    amount: Float(required=True, min_value=0.0)  # Positive amounts
```

**Common field validation parameters**:
- **All fields**: `required`, `default`, `unique`, `choices`, `validators`
- **String**: `max_length`, `min_length`, `sanitize`
- **Integer/Float**: `min_value`, `max_value`

### Value object with field-level validation

Use field validators for single-field data type validations:

```python
class EmailValidator:
    def __init__(self):
        self.error = "Invalid email address"

    def __call__(self, value):
        if "@" not in value or value.startswith("@"):
            raise ValidationError(self.error)


@domain.value_object
class Email:
    address: String(
        max_length=254,
        required=True,
        validators=[EmailValidator()]
    )
```

**When to use field validators**: For single-field format validations (email format, phone format, etc.). For business rules involving multiple fields, use invariants instead.

### Value object with methods

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    def add(self, other: "Money") -> "Money":
        """Add two Money values, ensuring same currency."""
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        # Return NEW instance (immutability)
        return Money(
            currency=self.currency,
            amount=self.amount + other.amount
        )

    def multiply(self, factor: float) -> "Money":
        """Multiply money by a factor."""
        return Money(
            currency=self.currency,
            amount=self.amount * factor
        )
```

### Value object with invariants

**Important principle**: All business validations involving cross-field logic should be codified as invariants, as granularly as possible. Each invariant should check a single business rule.

Value objects only support `@invariant.post` (since they're immutable and created atomically). Invariants run automatically after initialization.

```python
from protean import invariant

@domain.value_object
class DateRange:
    start_date: String(required=True)
    end_date: String(required=True)

    @invariant.post
    def end_must_be_after_start(self):
        """Granular business rule: date ordering.

        Each invariant validates ONE constraint clearly.
        """
        if self.end_date < self.start_date:
            raise ValidationError(
                {"date_range": ["End date must be after start date"]}
            )


@domain.value_object
class Money:
    # Use field-level validation for data type constraints
    currency: String(max_length=3, min_length=3, required=True)
    amount: Float(required=True, min_value=0.0)  # Enforces positive amounts

    @invariant.post
    def currency_must_be_valid_ISO_code(self):
        """Granular business rule: currency validation.

        Use invariants for business logic beyond simple data type constraints.
        Keep invariants focused - one rule per constraint.
        """
        valid_currencies = ["USD", "EUR", "GBP", "JPY"]
        if self.currency not in valid_currencies:
            raise ValidationError(
                {"currency": [f"Currency must be one of {valid_currencies}"]}
            )
```

**Best practices for value object invariants**:
1. **One rule per invariant** - Keep them granular and focused
2. **Use descriptive names** - Clearly describe the business constraint
3. **Only `@invariant.post`** - Pre invariants don't apply to immutable objects
4. **Prefer field validations first** - Use field parameters (`min_value`, `max_value`, etc.) for data type constraints
5. **Use invariants for business logic** - Cross-field validations, domain-specific rules, complex validations
6. **Example**: `amount > 0` → Use `Float(min_value=0.01)` (field validation), not invariant
7. **Example**: `end_date > start_date` → Use `@invariant.post` (cross-field business rule)

## Embedding in aggregates and entities

### In aggregates

```python
@domain.aggregate
class Account:
    balance = ValueObject(Balance, required=True)
    account_number: String(required=True, max_length=20)
```

### In entities

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        """Calculate line total using Money's multiply method."""
        return self.unit_price.multiply(self.quantity)
```

### Multiple value objects

```python
@domain.aggregate
class Order:
    order_number: String(required=True, identifier=True)
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)
    total = ValueObject(Money, required=True)
    discount = ValueObject(Money)  # Optional
```

## Initialization patterns

### Initialize with complete object

```python
account = Account(
    balance=Balance(currency="USD", amount=100.0),
    account_number="ACC-12345"
)
```

### Initialize by attributes

```python
# Attribute names: {field_name}_{vo_field_name}
account = Account(
    balance_currency="USD",
    balance_amount=100.0,
    account_number="ACC-12345"
)
```

Both approaches produce identical results. Attribute initialization only works during entity/aggregate creation, not for updating value objects later.

## Nested value objects

Value objects can contain other value objects:

```python
@domain.value_object
class Coordinates:
    latitude: Float(required=True, min_value=-90.0, max_value=90.0)
    longitude: Float(required=True, min_value=-180.0, max_value=180.0)


@domain.value_object
class Address:
    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)
    coordinates = ValueObject(Coordinates)  # Nested VO


# Initialize with nested objects
address = Address(
    street="123 Broadway",
    city="New York",
    state="NY",
    postal_code="10012",
    country="USA",
    coordinates=Coordinates(latitude=40.7128, longitude=-74.0060)
)

# Or by attributes
address = Address(
    street="123 Broadway",
    city="New York",
    state="NY",
    postal_code="10012",
    country="USA",
    coordinates_latitude=40.7128,
    coordinates_longitude=-74.0060
)
```

## Immutability

Value objects cannot be modified after creation:

```python
balance = Balance(currency="USD", amount=100.0)

# This raises IncorrectUsageError
balance.currency = "EUR"

# This also raises IncorrectUsageError
balance.amount = 200.0
```

To "change" a value object, replace it entirely:

```python
account.balance = Balance(currency="USD", amount=200.0)
```

Methods in value objects must return NEW instances, not modify self:

```python
m1 = Money(currency="USD", amount=100.0)
m2 = Money(currency="USD", amount=50.0)

# add() returns NEW Money instance
m3 = m1.add(m2)

# Originals unchanged
assert m1.amount == 100.0
assert m2.amount == 50.0
assert m3.amount == 150.0
```

## Equality

Two value objects with the same attribute values are equal:

```python
bal1 = Balance(currency="USD", amount=100.0)
bal2 = Balance(currency="USD", amount=100.0)
bal3 = Balance(currency="EUR", amount=100.0)

assert bal1 == bal2  # True - same values
assert bal1 == bal3  # False - different currency
```

This is fundamentally different from entities, where identity matters:
- **Value Object**: Same values → Equal
- **Entity**: Same ID → Equal (even if other attributes differ)

## Common mistakes

- **Trying to modify value objects** — VOs are immutable. Replace the entire VO instead: `account.balance = Balance(currency="USD", amount=200.0)`
- **Adding identity fields** — VOs cannot have `identifier=True` or `Auto()`. Use Entity if you need identity.
- **Using primitives instead of VOs** — Use `total = ValueObject(Money)` instead of separate `total_amount`/`total_currency` fields.
- **Methods that modify self** — Always return NEW instances: `return Money(amount=self.amount + other.amount)`
- **Not using invariants for cross-field validations** — Use `@invariant.post` instead of `__init__` validation.

See [Anti-patterns](references/anti-patterns.md) for detailed examples of each mistake.

### What `check` reports

`check` inspects your value objects and reports this diagnostic:

- `VALUE_OBJECT_MUTABLE_FIELD`: the value object has a mutable collection field (such as a `List`), which breaks its value semantics. Replace it with an immutable representation, or move the collection onto the containing entity or aggregate. If the values carry their own identity, model them as an entity.

A second diagnostic surfaces at runtime. It depends on the values a value object is built from, so `check` cannot report it statically:

- `VALUE_OBJECT_INVARIANT_FAILED`: an `@invariant.post` on the value object did not hold when it was built, so construction raised a `ValidationError` carrying this code. It is the default code for a failed post-invariant; an invariant declared with `@invariant.post(code=...)` carries that code instead. Build the value object from values that satisfy its invariants, or catch the `ValidationError`. The messages on the error are the ones the invariant itself raised, keyed by field.

## Quick example

Complete example with aggregate, entity, and value objects:

```python
from protean import Domain
from protean.fields import Float, Integer, String, ValueObject, HasMany

domain = Domain(__name__)


@domain.value_object
class Money:
    """Money with currency and amount."""
    currency: String(max_length=3, default="USD")
    amount: Float(default=0.0)

    def multiply(self, factor: float) -> "Money":
        return Money(currency=self.currency, amount=self.amount * factor)

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Currency mismatch")
        return Money(currency=self.currency, amount=self.amount + other.amount)


@domain.entity(part_of="Order")
class OrderLine:
    """Order line item with money value object."""
    product_id: String(required=True, max_length=50)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        return self.unit_price.multiply(self.quantity)


@domain.aggregate
class Order:
    """Order aggregate using value objects."""
    order_number: String(required=True, max_length=20, identifier=True)
    line_items = HasMany(OrderLine)

    def calculate_total(self) -> Money:
        if not self.line_items:
            return Money(currency="USD", amount=0.0)

        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = total.add(item.line_total)

        return total
```

## Examples

- [Simple value object](assets/value_object_simple.py): a minimal value object

## Detailed references

- [Value Objects with Validation](references/with-validation.md) - Custom validators and validation patterns
- [Value Objects with Methods](references/with-methods.md) - Adding business logic and operations
- [Value Objects with Invariants](references/with-invariants.md) - Cross-field validation rules
- [Nested Value Objects](references/nested-value-objects.md) - Composition and nesting patterns
- [Value Objects in Aggregates](references/in-aggregates.md) - Using VOs in aggregates
- [Value Objects in Entities](references/in-entities.md) - Using VOs in entities
- [Equality and Immutability](references/equality-and-immutability.md) - Core concepts explained
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

## Related skills

- [aggregate](../aggregate/SKILL.md) - Aggregates contain value objects
- [entity](../entity/SKILL.md) - Entities contain value objects

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
