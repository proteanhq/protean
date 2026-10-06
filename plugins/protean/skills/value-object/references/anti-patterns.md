# Value Object Anti-Patterns

This reference documents common mistakes and anti-patterns when working with value objects. Learn what NOT to do and why, along with correct alternatives.

## Overview

Common anti-patterns:
- Using primitives instead of value objects (Primitive Obsession)
- Trying to modify immutable value objects
- Adding identity to value objects
- Anemic value objects without behavior
- Value objects referencing entities
- Overusing or underusing value objects

## Primitive Obsession

### Anti-Pattern: Flattening to Primitives

**❌ Bad: Using primitives everywhere**
```python
# fragment
@domain.aggregate
class Order:
    customer_id: String(required=True)

    # Flattened money
    total_amount: Decimal(precision=19, scale=4)
    total_currency: String()

    # Flattened address
    shipping_street: String()
    shipping_city: String()
    shipping_state: String()
    shipping_postal_code: String()
    shipping_country: String()
```

**Problems:**
- No encapsulation of validation
- Related fields scattered
- Difficult to maintain consistency
- Business rules duplicated across code

**✅ Good: Using value objects**
```python
from decimal import Decimal as D


@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True, min_value=0)


@domain.value_object
class Address:
    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)
```

**Benefits:**
- Validation encapsulated
- Related fields grouped
- Easier to maintain
- Business rules in one place

## Attempting to Modify Immutable Objects

### Anti-Pattern: Trying to Change Value Objects

**❌ Bad: Modifying value object attributes**
```python
import pytest

from protean.exceptions import IncorrectUsageError

total = Money(currency="USD", amount=D("100.00"))

# Assigning to a value object's attribute raises IncorrectUsageError
with pytest.raises(IncorrectUsageError):
    total.amount = D("200.00")

with pytest.raises(IncorrectUsageError):
    total.currency = "EUR"
```

**✅ Good: Replacing entire value object**
```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(
        customer_id="CUST-001",
        total=Money(currency="USD", amount=D("100.00")),
        shipping_address=Address(
            street="123 Main St",
            city="Boston",
            state="MA",
            postal_code="02101",
            country="USA",
        ),
    )

    # Create new instance and replace
    order.total = Money(currency="USD", amount=D("200.00"))
```

A value object method that returns a new instance works the same way: `order.total = order.total.multiply(D("0.9"))`. See [Anemic Value Objects](#anemic-value-objects) for such a method.

### Anti-Pattern: Methods That Modify Self

**❌ Bad: Modifying self in methods**
```python
# fragment
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

    def add(self, other: "Money") -> "Money":
        # Wrong! Trying to modify self
        self.amount += other.amount
        return self
```

**✅ Good: Methods return new instances**
```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

    def add(self, other: "Money") -> "Money":
        # Correct: Return new instance
        return Money(
            currency=self.currency,
            amount=self.amount + other.amount
        )
```

## Adding Identity to Value Objects

### Anti-Pattern: Identity Fields in Value Objects

**❌ Bad: Adding ID fields**
```python
# fragment
@domain.value_object
class Address:
    id: Auto(identifier=True)  # Error! Value objects can't have identity
    street: String(required=True)
    city: String(required=True)
```

**❌ Bad: Marking fields as identifier**
```python
# fragment
@domain.value_object
class Email:
    address: String(identifier=True)  # Error!
```

**❌ Bad: Marking fields as unique**
```python
# fragment
@domain.value_object
class PhoneNumber:
    number: String(unique=True)  # Error!
```

**Why it's wrong:**
- Value objects are identified by their attributes, not by an ID
- Two VOs with same attributes ARE the same value
- Identity defeats the purpose of value objects

**✅ Good: If you need identity, use an Entity**
```python
@domain.entity(part_of="Customer")
class ContactMethod:
    # Entities can have identity
    contact_id: String(identifier=True)
    email: String(required=True)
    phone: String()
```

## Anemic Value Objects

### Anti-Pattern: Value Objects Without Behavior

**❌ Bad: Just data, no behavior**
```python
# fragment
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)
    # No methods!


# Business logic scattered across aggregates
@domain.aggregate
class Order:
    total = ValueObject(Money)

    def calculate_discount(self, percentage: D) -> Money:
        # Logic that should be in Money
        discounted_amount = self.total.amount * (1 - percentage)
        return Money(
            currency=self.total.currency,
            amount=discounted_amount
        )
```

**✅ Good: Value objects with behavior**
```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

    def multiply(self, factor: int | D) -> "Money":
        return Money(
            currency=self.currency,
            amount=(self.amount * factor).quantize(D("0.0001"))
        )

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(
            currency=self.currency,
            amount=self.amount + other.amount
        )


@domain.aggregate
class Order:
    total = ValueObject(Money)

    def calculate_discount(self, percentage: D) -> Money:
        # Use value object's behavior
        return self.total.multiply(1 - percentage)
```

## Value Objects Referencing Entities

### Anti-Pattern: Value Objects with Entity References

**❌ Bad: Referencing entities**
```python
# fragment
@domain.value_object
class OrderSummary:
    order_id: String()  # Reference to Order entity
    customer_id: String()  # Reference to Customer entity
    total: Decimal(precision=19, scale=4)

    # This couples VO to entities - wrong!
```

**Why it's wrong:**
- Value objects should be self-contained
- Creates coupling between VOs and entities
- Violates value object independence
- Makes VOs harder to reuse

**✅ Good: Self-contained value objects**
```python
@domain.value_object
class Money:
    # Self-contained, no entity references
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)


@domain.aggregate
class Order:
    # Aggregate contains VOs and entity references
    order_id: String(identifier=True)
    customer_id: Identifier(required=True)  # Another aggregate, held by id
    total = ValueObject(Money)
```

## Missing Validation

### Anti-Pattern: No Validation in Value Objects

**❌ Bad: Accepting invalid values**
```python
# fragment
@domain.value_object
class Email:
    address: String(max_length=254)
    # No validation!

# Invalid emails can be created
email = Email(address="not-an-email")  # Should fail!
email = Email(address="")  # Should fail!
```

**✅ Good: Validation built-in**
```python
from protean.exceptions import ValidationError
from protean.fields.validators import RegexValidator


@domain.value_object
class Email:
    address: String(
        max_length=254,
        required=True,
        validators=[RegexValidator(r"^[^@\s]+@[^@\s]+$", message="Invalid email address")]
    )

# Invalid emails are rejected
try:
    email = Email(address="not-an-email")
except ValidationError as exc:
    print(exc.messages)  # {'address': ['Invalid email address']}
```

## Wrong Aggregate/Entity/Value Object Choice

### Anti-Pattern: Value Object Should Be Entity

**❌ Bad: Using VO when identity matters**
```python
# fragment
@domain.value_object
class Customer:
    name: String()
    email: String()
    # Customers have identity! Should be entity/aggregate
```

**Signals it should be entity:**
- Has lifecycle (created, updated, deleted)
- Identity matters more than attributes
- Two customers with same name are different people

**✅ Good: Use aggregate or entity**
```python
@domain.aggregate
class Customer:
    customer_id: String(identifier=True)
    name: String()
    email = ValueObject(Email)  # Email is VO, Customer is aggregate
```

### Anti-Pattern: Entity Should Be Value Object

**❌ Bad: Using entity when no identity needed**
```python
# fragment
@domain.entity(part_of="Order")
class Money:
    id: Auto()  # Money doesn't need identity!
    currency: String()
    amount: Decimal(precision=19, scale=4)
```

**Signals it should be value object:**
- No meaningful identity
- Two instances with same values are the same
- Immutable by nature
- Descriptive, not behavioral with state

**✅ Good: Use value object**
```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)
```

## Over-nesting Value Objects

### Anti-Pattern: Too Many Nesting Levels

**❌ Bad: Excessive nesting**
```python
# fragment
@domain.value_object
class Unit:
    number: String()


@domain.value_object
class Floor:
    unit = ValueObject(Unit)


@domain.value_object
class Building:
    floor = ValueObject(Floor)


@domain.value_object
class Street:
    building = ValueObject(Building)


@domain.value_object
class Address:
    street = ValueObject(Street)  # 5 levels deep!
```

**Problems:**
- Hard to initialize
- Difficult to work with
- Confusing structure
- Over-engineered

**✅ Good: Reasonable nesting (2-3 levels max)**
```python
@domain.value_object
class StreetAddress:
    street_number: String(required=True)
    street_name: String(required=True)
    unit: String()  # Flattened


@domain.value_object
class Address:
    street_address = ValueObject(StreetAddress)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)
```

## Not Using Value Object Methods

### Anti-Pattern: Reimplementing VO Logic

**❌ Bad: Duplicating VO behavior in aggregate**
```python
# fragment
@domain.aggregate
class Order:
    line_items = HasMany("LineItem")

    def calculate_total(self) -> D:
        # Reimplementing Money logic
        total = D("0")
        for item in self.line_items:
            total += item.unit_price.amount * item.quantity
        return total
```

**✅ Good: Using VO methods**

This example uses the `Money` class with `multiply` and `add` from [Anemic Value Objects](#anemic-value-objects).

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        return self.unit_price.multiply(self.quantity)


@domain.aggregate
class Order:
    line_items = HasMany(LineItem)

    def calculate_total(self) -> Money:
        # Using Money's methods
        if not self.line_items:
            return Money(currency="USD", amount=D("0"))

        total = self.line_items[0].line_total
        for item in self.line_items[1:]:
            total = total.add(item.line_total)

        return total
```

## Vague Error Messages

### Anti-Pattern: Unclear Validation Errors

**❌ Bad: Vague errors**
```python
# fragment
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Invalid")  # Too vague!
```

**✅ Good: Clear, specific errors**
```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot add different currencies: "
                f"{self.currency} and {other.currency}"
            )
```

## Summary: Quick Checks

**Before creating a value object, ask:**
- ✅ Does it have identity? → Use Entity/Aggregate instead
- ✅ Will it need to change? → Use Entity/Aggregate instead
- ✅ Is it self-contained? → Don't reference entities
- ✅ Does it have validation? → Add validators/invariants
- ✅ Does it have behavior? → Add methods
- ✅ Is nesting reasonable? → Keep to 2-3 levels max

**After creating a value object, verify:**
- ✅ No identity fields
- ✅ Has validation logic
- ✅ Has relevant methods
- ✅ Methods return new instances
- ✅ Clear error messages
- ✅ No entity references
- ✅ Used instead of primitives

## Related

- [Equality and Immutability](./equality-and-immutability.md) - Core concepts
- [Value Objects with Methods](./with-methods.md) - Adding behavior
- [Value Objects with Validation](./with-validation.md) - Validation patterns
- [Deciding Between Elements](https://docs.proteanhq.com/concepts/building-blocks/choosing-element-types/) - When to use VOs vs Entities
