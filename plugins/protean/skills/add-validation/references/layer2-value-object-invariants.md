# Layer 2: Value Object Invariants

Value object invariants enforce rules inherent to a domain concept — rules that must always be true for any instance of that concept, regardless of which aggregate uses it.

## Code

The complete implementation is in [assets/validation_layer2_vo_invariants.py](../assets/validation_layer2_vo_invariants.py).

## Pattern

```python
from protean import invariant
from protean.exceptions import ValidationError

@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)

    @invariant.post
    def amount_must_be_non_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})
```

## Key Principles

1. **Only `@invariant.post`** — Value objects are immutable, so pre-invariants don't apply
2. **One rule per invariant** — Keep them granular and focused
3. **Descriptive names** — Name as business rules: `end_must_be_after_start`
4. **Raise with field context** — Use `{"field_name": ["message"]}` format
5. **Field constraints first** — Use `Float(min_value=0)` before writing an invariant

## When to Use Layer 2

- Cross-field VO rules: "end date after start date", "amount matches currency rules"
- Concept-level rules: "valid ISO currency code", "coordinate in valid range"
- Rules intrinsic to the concept, not specific to any aggregate

## Validation Timing

1. All field constraints run first (Layer 1)
2. If field validation passes, post-invariants run
3. If field validation fails, invariants are **skipped** (no false positives)

This prevents confusing errors when basic data is wrong.

## Common Patterns

### Date ordering
```python
@invariant.post
def end_must_be_after_start(self):
    if self.end_date <= self.start_date:
        raise ValidationError({"date_range": ["End must be after start"]})
```

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

- [Layer 1](./layer1-field-constraints.md) - Field constraints (use first)
- [Layer 3](./layer3-aggregate-invariants.md) - Aggregate invariants
