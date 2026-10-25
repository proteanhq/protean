# Layer 3: Aggregate Invariants

Aggregate invariants enforce business rules across an aggregate's state, including cross-field consistency, collection constraints, and state machine guards.

## Two Types of Invariants

### `@invariant.post`: After-change consistency

Checked after initialization AND after each attribute change. Use for rules about what the aggregate's state should look like. The `Order` in the SKILL.md shows two: `total_must_equal_sum_of_items` and `must_have_items_when_placed`.

### `@invariant.pre`: Before-change guards

Checked BEFORE attribute changes on an object that already exists. Pre-invariants do NOT run during `__init__`. Use for rules about what state changes are allowed, such as `cannot_modify_shipped_order` in the SKILL.md.

## Common Patterns

### Cross-field bounds
```python
@invariant.post
def reserved_cannot_exceed_stock(self):
    if self.reserved > self.current_stock:
        raise ValidationError({"reserved": ["Exceeds current stock"]})
```

## Entity Invariants

Entities within an aggregate can also have invariants. They run as part of the aggregate's validation chain.

```python
from protean import invariant
from protean.exceptions import ValidationError
from protean.fields import Decimal, HasMany, Integer


@domain.entity(part_of="Order")
class OrderItem:
    quantity: Integer(required=True)
    price: Decimal(precision=19, scale=4, required=True)

    @invariant.post
    def quantity_must_be_positive(self):
        if self.quantity <= 0:
            raise ValidationError({"quantity": ["Must be positive"]})


@domain.aggregate
class Order:
    items = HasMany("OrderItem")
```

## Atomic Changes

Without `atomic_change`, each assignment triggers validation, which may fail for intermediate states. With `with atomic_change(order):`, pre-invariants run once when the block opens, and post-invariants run once when it exits. The SKILL.md shows the full example.

## Related

- [Layer 2](./layer2-value-object-invariants.md): VO invariants (concept rules)
- [Layer 4](./layer4-handler-guards.md): Handler guards (context rules)
- [Choosing the Right Layer](./choosing-the-right-layer.md): Decision framework
