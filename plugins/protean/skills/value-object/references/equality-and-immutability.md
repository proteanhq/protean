# Equality and Immutability

Two fundamental characteristics define value objects: they are compared by their attribute values (equality) and they cannot be changed once created (immutability). Understanding these concepts is essential to using value objects correctly.

## Overview

Key concepts:
- **Equality**: Two value objects with same attributes are equal
- **Immutability**: Value objects cannot be modified after creation
- **No Identity**: Value objects have no unique identifier
- **Interchangeability**: Equal value objects can be swapped freely

## Equality

### Value-Based Equality

Value objects are equal when all their attributes match. A Decimal amount matches only in the
same exact form (see [Decimal Amounts Compare by Their Exact Form](#decimal-amounts-compare-by-their-exact-form)):

```python
from decimal import Decimal as D

from protean.exceptions import IncorrectUsageError


@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)


# Two instances with same values
m1 = Money(currency="USD", amount=D("100.00"))
m2 = Money(currency="USD", amount=D("100.00"))

# They are equal
assert m1 == m2

# Different values are not equal
m3 = Money(currency="EUR", amount=D("100.00"))
assert m1 != m3
```

This is fundamentally different from entities, where identity matters:

```python
@domain.aggregate
class Order:
    items = HasMany("LineItem")


@domain.entity(part_of=Order)
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)


domain.init(traverse=False)

with domain.domain_context():
    # Two entities with same attributes but different IDs
    item1 = LineItem(product_id="PROD-1", quantity=5)
    item2 = LineItem(product_id="PROD-1", quantity=5)

    # They are NOT equal (different identities)
    assert item1 != item2
```

### All Attributes Matter

ALL attributes must match for equality:

```python
@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)

addr1 = Address(
    street="123 Main St",
    city="Boston",
    state="MA",
    postal_code="02101"
)

addr2 = Address(
    street="123 Main St",
    city="Boston",
    state="MA",
    postal_code="02101"
)

# All attributes match
assert addr1 == addr2

addr3 = Address(
    street="123 Main St",  # Same street
    city="Boston",
    state="MA",
    postal_code="02102"    # Different postal code
)

# One attribute differs
assert addr1 != addr3
```

### Decimal Amounts Compare by Their Exact Form

A value object compares its `to_dict()` output, and `to_dict()` turns a `decimal.Decimal`
into its string. So `D("1.0")` and `D("1.00")`, which are equal as numbers, make two
unequal value objects:

```python
assert Money(currency="USD", amount=D("1.0")) != Money(currency="USD", amount=D("1.00"))

# Quantize to the field's scale before building the value object
FOUR_PLACES = D("0.0001")
assert Money(currency="USD", amount=D("1.0").quantize(FOUR_PLACES)) == Money(
    currency="USD", amount=D("1.00").quantize(FOUR_PLACES)
)
```

The same applies to a value read back from a database, which may come back with a different
number of decimal places, and to a `default=0`, which the field keeps as the int `0`.
Quantize amounts in the methods that build them, as `with-methods.md` does.

### Nested Value Objects

Equality cascades through nested value objects:

```python
@domain.value_object
class Coordinates:
    latitude: Float(required=True)
    longitude: Float(required=True)


@domain.value_object
class Location:
    name: String(required=True)
    coordinates = ValueObject(Coordinates)

loc1 = Location(
    name="Office",
    coordinates=Coordinates(latitude=40.7, longitude=-74.0)
)

loc2 = Location(
    name="Office",
    coordinates=Coordinates(latitude=40.7, longitude=-74.0)
)

# Deep equality - nested VOs also compared
assert loc1 == loc2
```

## Immutability

### Cannot Modify After Creation

Value objects cannot be changed once created:

```python
money = Money(currency="USD", amount=D("100.00"))

try:
    money.currency = "EUR"
except IncorrectUsageError:
    print("Cannot change currency")

try:
    money.amount = D("200.00")
except IncorrectUsageError:
    print("Cannot change amount")
```

### Replace Instead of Modify

To "change" a value object, create a new instance:

```python
# Original value object
price = Money(currency="USD", amount=D("100.00"))

# Cannot modify
# price.amount = D("200.00")  # Raises IncorrectUsageError

# Replace with new instance
price = Money(currency="USD", amount=D("200.00"))
```

On an aggregate, assign the new instance to the field. See [Immutability in Aggregates](#immutability-in-aggregates).

### Why Immutability Matters

Immutability provides several benefits:

**1. Thread Safety**
```python
# Value objects can be safely shared between threads
shared_price = Money(currency="USD", amount=D("50.00"))

# Multiple threads can read without locks
# No thread can modify it
```

**2. Predictable Behavior**
```python
def calculate_discount(price: Money, rate: D) -> Money:
    # price parameter won't be modified
    # Safe to use without defensive copying
    amount = (price.amount * (1 - rate)).quantize(D("0.0001"))
    return Money(currency=price.currency, amount=amount)

original_price = Money(currency="USD", amount=D("100.00"))
discounted = calculate_discount(original_price, D("0.1"))

# original_price unchanged
assert original_price.amount == D("100.00")
assert discounted.amount == D("90.00")
```

**3. Safe Caching**
```python
# Value objects can be cached safely
cache = {}

address = Address(street="123 Main St", city="Boston", state="MA", postal_code="02101")
cache[address] = "Delivery zone 3"  # the result of an expensive lookup

# Address can't change, so cache entry remains valid.
# An equal address finds the same entry.
assert cache[Address(street="123 Main St", city="Boston", state="MA", postal_code="02101")] == "Delivery zone 3"
```

### Methods Return New Instances

Value object methods that "modify" values return NEW instances:

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

    def add(self, other: "Money") -> "Money":
        # Returns NEW instance
        return Money(
            currency=self.currency,
            amount=self.amount + other.amount
        )

m1 = Money(currency="USD", amount=D("100.00"))
m2 = Money(currency="USD", amount=D("50.00"))

# add() returns new instance
m3 = m1.add(m2)

# Original instances unchanged
assert m1.amount == D("100.00")
assert m2.amount == D("50.00")
assert m3.amount == D("150.00")
```

### Immutability in Aggregates

When value objects are embedded in aggregates, replace them entirely:

```python
@domain.aggregate
class Account:
    balance = ValueObject(Money)

domain.init(traverse=False)

with domain.domain_context():
    account = Account(balance=Money(currency="USD", amount=D("1000.00")))

    # Cannot modify VO attribute
    # account.balance.amount = D("1500.00")  # Raises IncorrectUsageError

    # Replace entire VO
    account.balance = Money(currency="USD", amount=D("1500.00"))

    # Or pass the VO's fields flattened, one level deep (only at creation)
    account = Account(balance_currency="USD", balance_amount=D("1000.00"))
```

## No Identity

### Value Objects Have No ID

Unlike entities and aggregates, value objects don't have identity fields:

```python
@domain.value_object
class Price:
    # Cannot use identifier=True
    # id: String(identifier=True)  # Raises IncorrectUsageError

    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)
```

Marking a field as the identifier raises `IncorrectUsageError` when the class is registered:

```python
import pytest

with pytest.raises(IncorrectUsageError):

    @domain.value_object
    class Address:
        id: Auto(identifier=True)  # Value objects cannot have identity fields
        street: String()
```

A plain `Auto()` field without `identifier=True` is accepted. It is not an identity: it generates a new value for every instance, and that value takes part in equality, so two addresses with the same street compare unequal. Leave such fields out of value objects.

### Value Objects Cannot Be Unique

Cannot mark fields as unique:

```python
@domain.value_object
class Email:
    # Cannot use unique=True
    # address: String(unique=True)  # Raises IncorrectUsageError

    address: String(max_length=254, required=True)
```

### Interchangeability

Because value objects have no identity, equal instances are interchangeable:

```python
@domain.aggregate
class Order:
    shipping_address = ValueObject(Address)


domain.init(traverse=False)

# Two equal addresses
addr1 = Address(street="123 Main St", city="Boston", state="MA", postal_code="02101")
addr2 = Address(street="123 Main St", city="Boston", state="MA", postal_code="02101")

with domain.domain_context():
    order = Order(shipping_address=addr1)

    # Can swap with equal VO
    order.shipping_address = addr2

# No meaningful difference - they're equal
assert addr1 == addr2
```

## Practical Implications

### In Collections

Value objects can be used in sets because equality is well-defined:

```python
addresses = set()
addresses.add(Address(street="123 Main St", city="Boston", state="MA", postal_code="02101"))
addresses.add(Address(street="123 Main St", city="Boston", state="MA", postal_code="02101"))  # Same values

# Set contains only one address (they're equal)
assert len(addresses) == 1
```

### As Dictionary Keys

Value objects can be dictionary keys (with caution):

```python
shipping_costs = {
    Address(street="123 Main St", city="Boston", state="MA", postal_code="02101"): Money(currency="USD", amount=D("10.00")),
    Address(street="9 Elm St", city="Austin", state="TX", postal_code="73301"): Money(currency="USD", amount=D("15.00")),
}
```

A key can't change after it goes into the dictionary, because value objects are immutable.

### In Comparisons

```python
@domain.aggregate
class Order:
    shipping_address = ValueObject(Address)
    billing_address = ValueObject(Address)

    def uses_same_address_for_billing(self) -> bool:
        # Equality comparison
        return self.shipping_address == self.billing_address
```

## Testing Equality and Immutability

```python
import pytest


def test_value_object_equality():
    m1 = Money(currency="USD", amount=D("100.00"))
    m2 = Money(currency="USD", amount=D("100.00"))
    m3 = Money(currency="EUR", amount=D("100.00"))

    # Same values are equal
    assert m1 == m2
    # Different values are not equal
    assert m1 != m3

def test_value_object_immutability():
    money = Money(currency="USD", amount=D("100.00"))

    with pytest.raises(IncorrectUsageError):
        money.currency = "EUR"

    with pytest.raises(IncorrectUsageError):
        money.amount = D("200.00")

def test_methods_return_new_instances():
    m1 = Money(currency="USD", amount=D("100.00"))
    m2 = Money(currency="USD", amount=D("50.00"))

    m3 = m1.add(m2)

    # New instance created
    assert m3.amount == D("150.00")
    # Originals unchanged
    assert m1.amount == D("100.00")
    assert m2.amount == D("50.00")

def test_nested_value_object_equality():
    loc1 = Location(
        name="Office",
        coordinates=Coordinates(latitude=40.7, longitude=-74.0)
    )
    loc2 = Location(
        name="Office",
        coordinates=Coordinates(latitude=40.7, longitude=-74.0)
    )

    assert loc1 == loc2
```

## Common Mistakes

**Trying to modify value objects** ❌
```python
# fragment
money.amount = D("200.00")  # Raises IncorrectUsageError
```

**Expecting identity-based equality** ❌
```python
m1 = Money(currency="USD", amount=D("100.00"))
m2 = Money(currency="USD", amount=D("100.00"))

# Wrong assumption: they're different objects
if m1 is not m2:  # True, but misleading
    # They're EQUAL even though not same object
    assert m1 == m2  # True!
```

**Adding identity fields** ❌
```python
# fragment
@domain.value_object
class Money:
    id: Auto(identifier=True)  # IncorrectUsageError: VOs can't have identity
```

**Modifying then expecting changes** ❌
```python
# fragment
order.total.amount = D("200.00")  # Raises IncorrectUsageError
# Must replace entire VO
order.total = Money(currency="USD", amount=D("200.00"))
```

## Best Practices

1. **Test equality** - Verify VOs with same values are equal
2. **Test immutability** - Ensure modifications raise errors
3. **Replace, not modify** - Always create new instances
4. **Use in comparisons** - Leverage equality for business logic
5. **Document why immutable** - Help team understand the pattern
6. **No identity fields** - Never add IDs to value objects
7. **Return new from methods** - Never modify self

## Related

- [Value Objects with Methods](./with-methods.md) - Methods that return new instances
- [Value Objects in Aggregates](./in-aggregates.md) - Replacing VOs in aggregates
- [Anti-patterns](./anti-patterns.md) - Common equality/immutability mistakes
