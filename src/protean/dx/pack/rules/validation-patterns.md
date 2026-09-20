---
description: Validation patterns — field constraints vs invariants, validation layers, and where validation belongs
globs: "**/*.py"
---

# Validation Patterns

## Four Validation Layers

Protean has a layered validation model. Use the right layer for each constraint:

### Layer 1: Field Constraints

Single-field data constraints via field parameters. Checked automatically on construction
and mutation:

```python
@domain.aggregate
class Order:
    status = String(required=True, max_length=20, choices=["DRAFT", "PLACED", "SHIPPED"])
    quantity = Integer(min_value=1, max_value=10000)
    email = String(validators=[EmailValidator()])
```

### Layer 2: Value Object Invariants

Concept-level validation on value objects using `@invariant.post`. Ensures the value object
represents a valid domain concept:

```python
@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(required=True, max_length=3)

    @invariant.post
    def amount_must_be_non_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})
```

### Layer 3: Aggregate Invariants

Cross-field business rules on aggregates and entities using `@invariant.post`:

```python
@domain.aggregate
class Order:
    subtotal = Float()
    discount = Float(default=0.0)

    @invariant.post
    def discount_cannot_exceed_subtotal(self):
        """Discount must not exceed the order subtotal."""
        if self.discount > self.subtotal:
            raise ValidationError(
                {"discount": ["Discount cannot exceed subtotal"]}
            )
```

### Layer 4: Aggregate Method Guards

Pre-condition checks inside business methods — validate state before performing an action:

```python
@domain.aggregate
class Order:
    def ship(self):
        if self.status != "PLACED":
            raise ValidationError(
                {"status": [f"Cannot ship order in {self.status} status"]}
            )
        self.status = "SHIPPED"
        self.raise_(OrderShipped(...))
```

## Decision Framework

- **Single field, data constraint** -> Field parameter (`required`, `max_length`, `min_value`, `choices`, `validators`)
- **Value object concept validity** -> `@invariant.post` on the value object
- **Cross-field business rule** -> `@invariant.post` on the aggregate/entity
- **State-dependent pre-condition** -> Guard clause in the aggregate method
- **Never duplicate** a field constraint as an invariant
