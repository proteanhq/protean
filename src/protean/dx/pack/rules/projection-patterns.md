---
description: Projection patterns — basic fields only, projector wiring, and read model rules
globs: "**/*.py"
---

# Projection Patterns

## Basic Fields Only

Projections support only basic field types: `String`, `Integer`, `Float`, `Identifier`,
`DateTime`, `Boolean`, `Text`, `Date`, `Auto`. No `Reference`, `HasOne`, `HasMany`, or
`ValueObject`:

```python
@domain.projection
class OrderSummary:
    order_id = Identifier(identifier=True)
    customer_name = String()
    total_amount = Float()
    item_count = Integer()
    placed_at = DateTime()
```

## Projectors Use `@on`, Not `@handle`

Projectors use the `@on` decorator imported from `protean.core.projector`:

```python
from protean.core.projector import on

@domain.projector(projector_for=OrderSummary, stream_categories=[Order.meta_.stream_category])
class OrderSummaryProjector:
    @on(OrderPlaced)
    def on_order_placed(self, event):
        ...
```

## Projector Configuration

Projectors require both `projector_for` (the projection class) and either `aggregates`
or `stream_categories` (the event sources):

```python
# Single aggregate source
@domain.projector(projector_for=OrderSummary, aggregates=[Order])

# Multiple aggregate sources (cross-aggregate projection)
@domain.projector(
    projector_for=DashboardView,
    stream_categories=[Order.meta_.stream_category, Payment.meta_.stream_category],
)
```

## Must Have an Identifier

Every projection must have at least one field with `identifier=True`.
