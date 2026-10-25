# Layer 2: Value Object Invariants

Value object invariants enforce rules inherent to a domain concept: rules that must always be true for any instance of that concept, regardless of which aggregate uses it.

## Pattern

```python
from protean import invariant
from protean.exceptions import ValidationError
from protean.fields import Decimal, String

@domain.value_object
class Money:
    amount: Decimal(precision=19, scale=4, required=True)
    currency: String(max_length=3, required=True)

    @invariant.post
    def amount_must_be_non_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})
```

## Validation Timing

1. All field constraints run first (Layer 1)
2. If field validation passes, post-invariants run
3. If field validation fails, invariants are **skipped**, so you see only the field errors

## Common Patterns

### Valid enumeration (beyond choices)
```python
@invariant.post
def currency_must_be_supported(self):
    if self.currency not in VALID_CURRENCIES:
        raise ValidationError({"currency": [f"Unsupported: {self.currency}"]})
```

### Coordinate ranges
```python
@invariant.post
def latitude_must_be_valid(self):
    if not (-90.0 <= self.latitude <= 90.0):
        raise ValidationError({"latitude": ["Must be between -90 and 90"]})
```

## Related

- [Layer 1](./layer1-field-constraints.md): Field constraints (use first)
- [Layer 3](./layer3-aggregate-invariants.md): Aggregate invariants
