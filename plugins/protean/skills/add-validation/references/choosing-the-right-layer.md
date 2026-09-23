# Choosing the Right Validation Layer

A decision framework for placing validation rules in the correct Protean layer.

## Decision Tree

```
Is it a single-field data constraint?
├── Yes → Layer 1 (field parameters)
│   Examples: required, max_length, min_value, choices, validators=[]
│
└── No → Does it involve multiple fields?
    ├── Within a value object → Layer 2 (VO @invariant.post)
    │   Examples: end > start, amount >= 0 for currency
    │
    ├── Within an aggregate/entity → Layer 3 (aggregate invariants)
    │   │
    │   ├── Before change guard? → @invariant.pre
    │   │   Examples: cannot modify shipped, check balance before debit
    │   │
    │   └── After change consistency? → @invariant.post
    │       Examples: total = sum(items), must have items when placed
    │
    └── Needs external data or context? → Layer 4 (handler guard)
        Examples: authorization, existence checks, cross-aggregate rules
```

## Examples by Category

### Data format rules → Layer 1

| Rule | Implementation |
|------|----------------|
| "Name is required" | `name: String(required=True)` |
| "Age must be 18-120" | `age: Integer(min_value=18, max_value=120)` |
| "Status is draft/active/closed" | `status: String(choices=StatusEnum)` |
| "Email must be valid format" | `email: String(validators=[EmailValidator()])` |
| "Code must be XXX-NNNN" | `code: String(validators=[RegexValidator(...)])` |

### Domain concept rules → Layer 2

| Rule | Implementation |
|------|----------------|
| "End date after start date" | `@invariant.post` on DateRange VO |
| "Money amount non-negative" | `@invariant.post` on Money VO |
| "Currency must be valid ISO" | `@invariant.post` on Money VO |
| "Latitude in [-90, 90]" | `@invariant.post` on Coordinate VO |

### Business rules → Layer 3

| Rule | Implementation |
|------|----------------|
| "Total = sum of items" | `@invariant.post` on aggregate |
| "Cannot modify shipped order" | `@invariant.pre` on aggregate |
| "Must have items when placed" | `@invariant.post` on aggregate |
| "Reserved <= current stock" | `@invariant.post` on aggregate |
| "Balance above overdraft limit" | `@invariant.post` on aggregate |

### Context-dependent rules → Layer 4

| Rule | Implementation |
|------|----------------|
| "Only managers can create" | Guard in command handler |
| "Entity must exist" | `repo.get()` in handler |
| "Customer must be active" | Cross-aggregate check in handler |
| "Max 10 orders per day" | Quota check in handler |

## Anti-Patterns

### Don't put business rules in handlers

**Wrong**: Checking business rules in the handler
```python
# BAD: Business rule in handler
@handle(PlaceOrder)
def place_order(self, command):
    order = repo.get(command.order_id)
    if not order.items:  # Business rule leaked to handler!
        raise ValidationError({"items": ["Must have items"]})
    order.status = "placed"
```

**Right**: Business rule in aggregate invariant
```python
# GOOD: Business rule in aggregate
@invariant.post
def must_have_items_when_placed(self):
    if self.status != "draft" and not self.items:
        raise ValidationError({"items": ["Must have items"]})
```

### Don't duplicate constraints

**Wrong**: Invariant duplicating a field constraint
```python
# BAD: Duplicates min_value=0 field constraint
quantity: Integer(min_value=0)

@invariant.post
def quantity_must_be_non_negative(self):  # Redundant!
    if self.quantity < 0:
        raise ValidationError({"quantity": ["Must be non-negative"]})
```

### Don't use @invariant.pre on value objects

```python
# BAD: Pre-invariants don't apply to immutable VOs
@domain.value_object
class Money:
    @invariant.pre  # Will never run — VOs don't have mutable state
    def check_before_change(self):
        ...
```

## Complete Example

See [assets/validation_all_layers.py](../assets/validation_all_layers.py) for a full example showing all 4 layers working together in a realistic scenario.

## Related

- [Layer 1](./layer1-field-constraints.md)
- [Layer 2](./layer2-value-object-invariants.md)
- [Layer 3](./layer3-aggregate-invariants.md)
- [Layer 4](./layer4-handler-guards.md)
