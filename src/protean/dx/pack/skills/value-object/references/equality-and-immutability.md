# Equality and Immutability

A value object is compared by its attribute values and cannot be changed once created. It has no identity field.

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

Every attribute must match for two value objects to be equal:

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

Assigning to any field of a value object raises `IncorrectUsageError`. To change a value, build a new instance. A method that "changes" a value returns a new instance and leaves the original as it was; see [Value Objects with Methods](./with-methods.md).

### Why Immutability Matters

A value object is hashable, and it cannot change, so it can serve as a cache or dictionary key:

```python
# Value objects can be cached safely
cache = {}

address = Address(street="123 Main St", city="Boston", state="MA", postal_code="02101")
cache[address] = "Delivery zone 3"  # the result of an expensive lookup

# Address can't change, so cache entry remains valid.
# An equal address finds the same entry.
assert cache[Address(street="123 Main St", city="Boston", state="MA", postal_code="02101")] == "Delivery zone 3"
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

Marking a field `unique=True` raises `IncorrectUsageError` at registration in the same way: "Value Objects cannot contain fields marked 'unique'".

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

**Expecting identity-based equality** ❌
```python
m1 = Money(currency="USD", amount=D("100.00"))
m2 = Money(currency="USD", amount=D("100.00"))

# Wrong assumption: they're different objects
if m1 is not m2:  # True, but misleading
    # They're EQUAL even though not same object
    assert m1 == m2  # True!
```

## Related

- [Value Objects with Methods](./with-methods.md): Methods that return new instances
- [Value Objects in Aggregates](./in-aggregates.md): Replacing VOs in aggregates
- [Anti-patterns](./anti-patterns.md): Common equality/immutability mistakes
