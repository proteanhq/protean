# Common Value Objects

Catalog of frequently extracted value objects with implementation patterns.

## Money

The most common VO extraction. Whenever you see `amount` + `currency` (or just `price`/`cost` as a bare Float), extract to Money.

```python
@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def subtract(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(f"Cannot subtract {self.currency} and {other.currency}")
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def multiply(self, factor: int | float) -> "Money":
        return Money(amount=round(self.amount * factor, 2), currency=self.currency)

    def is_zero(self) -> bool:
        return self.amount == 0
```

## Address

Extract from `street` + `city` + `state` + `zip_code` + `country` groups.

```python
@domain.value_object
class Address:
    street = String(required=True, max_length=200)
    city = String(required=True, max_length=100)
    state = String(required=True, max_length=50)
    zip_code = String(required=True, max_length=20)
    country = String(max_length=100, default="US")

    def format_oneline(self) -> str:
        return f"{self.street}, {self.city}, {self.state} {self.zip_code}, {self.country}"
```

## Email

Extract from `String` fields with email validation or `_email` suffix.

```python
@domain.value_object
class Email:
    address = String(required=True, max_length=255)

    @invariant.post
    def must_be_valid_email(self):
        if self.address and "@" not in self.address:
            from protean.exceptions import ValidationError
            raise ValidationError({"address": ["Invalid email format"]})
```

## DateRange

Extract from `start_date` + `end_date` pairs.

```python
@domain.value_object
class DateRange:
    start = Date(required=True)
    end = Date(required=True)

    @invariant.post
    def end_must_be_after_start(self):
        if self.start and self.end and self.end < self.start:
            from protean.exceptions import ValidationError
            raise ValidationError({"end": ["End date must be after start date"]})

    @property
    def duration_days(self) -> int:
        return (self.end - self.start).days if self.start and self.end else 0
```

## Coordinates

Extract from `latitude` + `longitude` pairs.

```python
@domain.value_object
class Coordinates:
    latitude = Float(required=True)
    longitude = Float(required=True)

    @invariant.post
    def must_be_valid_coordinates(self):
        if self.latitude is not None and not (-90 <= self.latitude <= 90):
            from protean.exceptions import ValidationError
            raise ValidationError({"latitude": ["Must be between -90 and 90"]})
        if self.longitude is not None and not (-180 <= self.longitude <= 180):
            from protean.exceptions import ValidationError
            raise ValidationError({"longitude": ["Must be between -180 and 180"]})
```

## Percentage

Extract from bare `Float` fields representing percentages.

```python
@domain.value_object
class Percentage:
    value = Float(required=True)

    @invariant.post
    def must_be_in_range(self):
        if self.value is not None and not (0 <= self.value <= 100):
            from protean.exceptions import ValidationError
            raise ValidationError({"value": ["Must be between 0 and 100"]})

    def as_fraction(self) -> float:
        return self.value / 100
```

## Related

- [value-object SKILL.md](../../value-object/SKILL.md) — Full VO patterns
- [migration-guide.md](migration-guide.md) — How to migrate existing data
