# Layer 3: Aggregate Invariants

Aggregate invariants enforce business rules across an aggregate's state, including cross-field consistency, collection constraints, and state machine guards.

## Code

The complete implementation is in [assets/validation_layer3_aggregate_invariants.py](../assets/validation_layer3_aggregate_invariants.py).

## Two Types of Invariants

### `@invariant.post` — After-change consistency

Checked after initialization AND after each attribute change. Use for rules about what the aggregate's state should look like.

```python
@invariant.post
def total_must_equal_sum_of_items(self):
    """Aggregate consistency: total matches items."""
    if self.items:
        expected = sum(item.subtotal for item in self.items)
        if self.total_amount != expected:
            raise ValidationError({"_entity": ["Total mismatch"]})
```

### `@invariant.pre` — Before-change guards

Checked BEFORE attribute changes (NOT during initialization). Use for rules about what state changes are allowed.

```python
@invariant.pre
def cannot_modify_shipped_order(self):
    """State guard: shipped orders are frozen."""
    if self.status == "shipped":
        raise ValidationError({"_entity": ["Cannot modify shipped order"]})
```

**Important**: Pre-invariants do NOT run during `__init__`. They only run when changing attributes on an already-created object.

## Common Patterns

### Collection total consistency
```python
@invariant.post
def total_must_match_items(self):
    expected = sum(item.subtotal for item in self.items)
    if self.total != expected:
        raise ValidationError({"_entity": ["Total mismatch"]})
```

### State machine guard
```python
@invariant.pre
def cannot_modify_when_closed(self):
    if self.status == "closed":
        raise ValidationError({"_entity": ["Cannot modify closed entity"]})
```

### Minimum collection size
```python
@invariant.post
def must_have_items_when_active(self):
    if self.status != "draft" and not self.items:
        raise ValidationError({"items": ["Must have at least one item"]})
```

### Cross-field bounds
```python
@invariant.post
def reserved_cannot_exceed_stock(self):
    if self.reserved > self.current_stock:
        raise ValidationError({"reserved": ["Exceeds current stock"]})
```

## Atomic Changes

When changing multiple related fields, use `atomic_change` to defer validation:

```python
from protean import atomic_change

with atomic_change(order):
    order.total_amount = 120.0
    order.add_items(OrderItem(...))
# Invariants checked here, once, after all changes
```

Without `atomic_change`, each assignment triggers validation, which may fail for intermediate states.

## Entity Invariants

Entities within an aggregate can also have invariants. They run as part of the aggregate's validation chain.

```python
@domain.entity(part_of="Order")
class OrderItem:
    quantity: Integer(required=True)
    price: Float(required=True)

    @invariant.post
    def quantity_must_be_positive(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": ["Must be positive"]})
```

## Error Key Convention

- **Field-level errors**: `{"field_name": ["message"]}` — for a specific field
- **Entity-level errors**: `{"_entity": ["message"]}` — for aggregate-wide rules

## Related

- [Layer 2](./layer2-value-object-invariants.md) - VO invariants (concept rules)
- [Layer 4](./layer4-handler-guards.md) - Handler guards (context rules)
- [Choosing the Right Layer](./choosing-the-right-layer.md) - Decision framework
