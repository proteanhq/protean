# Value Objects with Methods

Value objects are not just data containers - they can and should encapsulate behavior related to their values. Methods in value objects implement business logic, provide computed properties, and maintain immutability through operations that return new instances.

## Overview

Add methods to value objects when:
- The concept has natural operations (add, subtract, multiply)
- You need computed properties derived from attributes
- Business logic operates on the value object's data
- You want to prevent invalid operations (like adding different currencies)

## Code

The complete implementation is in [assets/value_object_with_methods.py](../assets/value_object_with_methods.py).

Key highlights:
- Operations return new instances (maintaining immutability)
- Methods enforce business rules (e.g., same currency)
- Computed properties provide derived values
- Rich domain model with expressive operations

## Walkthrough

### Basic Operations

```python
@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount = Decimal(required=True, precision=2, scale=2)

    def add(self, other: "Money") -> "Money":
        """Add two Money values, ensuring same currency."""
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot add different currencies: {self.currency} and {other.currency}"
            )
        return Money(
            currency=self.currency,
            amount=self.amount + other.amount
        )
```

Key points:
- Method returns a NEW Money instance (immutability)
- Validates business rules (matching currencies)
- Type hints guide usage
- Clear error messages

### Mathematical Operations

```python
def subtract(self, other: "Money") -> "Money":
    """Subtract two Money values."""
    if self.currency != other.currency:
        raise ValueError(f"Cannot subtract different currencies")
    return Money(
        currency=self.currency,
        amount=self.amount - other.amount
    )

def multiply(self, factor: Decimal) -> "Money":
    """Multiply money by a factor."""
    return Money(
        currency=self.currency,
        amount=self.amount * factor
    )

def divide(self, divisor: Decimal) -> "Money":
    """Divide money by a divisor."""
    if divisor == 0:
        raise ValueError("Cannot divide by zero")
    return Money(
        currency=self.currency,
        amount=self.amount / divisor
    )
```

### Computed Properties

```python
@property
def is_positive(self) -> bool:
    """Check if amount is positive."""
    return self.amount > 0

@property
def is_zero(self) -> bool:
    """Check if amount is zero."""
    return self.amount == 0

@property
def is_negative(self) -> bool:
    """Check if amount is negative."""
    return self.amount < 0
```

Properties:
- Don't modify state
- Return derived information
- Make code more readable
- Can be used in conditionals

### Comparison Methods

```python
def is_greater_than(self, other: "Money") -> bool:
    """Compare if this money is greater than other."""
    if self.currency != other.currency:
        raise ValueError("Cannot compare different currencies")
    return self.amount > other.amount

def is_less_than(self, other: "Money") -> bool:
    """Compare if this money is less than other."""
    if self.currency != other.currency:
        raise ValueError("Cannot compare different currencies")
    return self.amount < other.amount
```

## Common Patterns

### Money Operations

The classic example - Money value object with mathematical operations:

```python
price = Money(currency="USD", amount=Decimal("100.00"))
tax = Money(currency="USD", amount=Decimal("8.75"))
total = price.add(tax)

# With discount
discount_rate = Decimal("0.10")  # 10%
discount = price.multiply(discount_rate)
final_price = price.subtract(discount)
```

### Date Range Operations

```python
@domain.value_object
class DateRange:
    start_date: String(required=True)
    end_date: String(required=True)

    @property
    def duration_days(self) -> int:
        """Calculate duration in days."""
        from datetime import datetime
        start = datetime.fromisoformat(self.start_date)
        end = datetime.fromisoformat(self.end_date)
        return (end - start).days

    def overlaps_with(self, other: "DateRange") -> bool:
        """Check if this range overlaps with another."""
        return not (self.end_date < other.start_date or
                    self.start_date > other.end_date)

    def contains_date(self, date: str) -> bool:
        """Check if a date falls within this range."""
        return self.start_date <= date <= self.end_date
```

### Coordinates with Distance Calculation

```python
@domain.value_object
class Coordinates:
    latitude: Float(required=True)
    longitude: Float(required=True)

    def distance_to(self, other: "Coordinates") -> float:
        """Calculate distance to another point using Haversine formula."""
        from math import radians, sin, cos, sqrt, atan2

        R = 6371  # Earth radius in km

        lat1, lon1 = radians(self.latitude), radians(self.longitude)
        lat2, lon2 = radians(other.latitude), radians(other.longitude)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))

        return R * c
```

### Weight with Unit Conversion

```python
@domain.value_object
class Weight:
    value: Float(required=True, min_value=0)
    unit: String(required=True, choices=['kg', 'lb', 'oz', 'g'])

    def to_kilograms(self) -> "Weight":
        """Convert to kilograms."""
        conversions = {
            'kg': 1.0,
            'lb': 0.453592,
            'oz': 0.0283495,
            'g': 0.001
        }
        kg_value = self.value * conversions[self.unit]
        return Weight(value=kg_value, unit='kg')

    def add(self, other: "Weight") -> "Weight":
        """Add two weights, converting to same unit."""
        # Convert both to kg, add, then convert back
        self_kg = self.to_kilograms()
        other_kg = other.to_kilograms()

        return Weight(
            value=self_kg.value + other_kg.value,
            unit='kg'
        )
```

## Usage in Entities and Aggregates

### In Entity Methods

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity = Decimal(required=True)
    unit_price = ValueObject(Money, required=True)

    @property
    def total(self) -> Money:
        """Calculate line total using Money's multiply method."""
        return self.unit_price.multiply(self.quantity)
```

### In Aggregate Methods

```python
@domain.aggregate
class Order:
    line_items = HasMany(LineItem)

    def calculate_total(self) -> Money:
        """Sum all line items using Money's add method."""
        if not self.line_items:
            return Money(currency="USD", amount=Decimal("0.00"))

        total = self.line_items[0].total
        for item in self.line_items[1:]:
            total = total.add(item.total)

        return total

    def apply_discount(self, percentage: Decimal) -> Money:
        """Calculate discounted total."""
        total = self.calculate_total()
        discount_factor = Decimal("1.0") - (percentage / Decimal("100.0"))
        return total.multiply(discount_factor)
```

## Testing Value Object Methods

Test all operations and edge cases:

```python
def test_money_addition():
    m1 = Money(currency="USD", amount=Decimal("100.00"))
    m2 = Money(currency="USD", amount=Decimal("50.00"))
    result = m1.add(m2)

    assert result.amount == Decimal("150.00")
    assert result.currency == "USD"
    # Original instances unchanged (immutability)
    assert m1.amount == Decimal("100.00")

def test_cannot_add_different_currencies():
    m1 = Money(currency="USD", amount=Decimal("100.00"))
    m2 = Money(currency="EUR", amount=Decimal("50.00"))

    with pytest.raises(ValueError) as exc:
        m1.add(m2)
    assert "different currencies" in str(exc.value)

def test_money_is_positive():
    m1 = Money(currency="USD", amount=Decimal("100.00"))
    m2 = Money(currency="USD", amount=Decimal("-50.00"))
    m3 = Money(currency="USD", amount=Decimal("0.00"))

    assert m1.is_positive is True
    assert m2.is_positive is False
    assert m3.is_positive is False
```

## Best Practices

1. **Return new instances** - Never modify self, always return new value object
2. **Validate operations** - Check preconditions (same currency, non-zero divisor)
3. **Use type hints** - Make operations self-documenting
4. **Keep methods focused** - One operation per method
5. **Name methods clearly** - `add`, `subtract`, `multiply` not `calc` or `process`
6. **Provide properties** - For derived/computed values
7. **Test thoroughly** - Operations are where bugs appear

## Common Mistakes

**Modifying self** ❌
```python
def add(self, other: "Money") -> "Money":
    self.amount += other.amount  # Wrong! Violates immutability
    return self
```

**Not validating operations** ❌
```python
def add(self, other: "Money") -> "Money":
    # Missing currency check!
    return Money(currency=self.currency, amount=self.amount + other.amount)
```

**Operations without return** ❌
```python
def add(self, other: "Money"):  # Missing return type
    # What does this return?
    pass
```

## Related

- [Value Objects with Validation](./with-validation.md) - Field-level validation
- [Value Objects with Invariants](./with-invariants.md) - Cross-field validation
- [Equality and Immutability](./equality-and-immutability.md) - Core concepts
- [Anti-patterns](./anti-patterns.md) - What not to do
