# Single-Aggregate Projector

A single-aggregate projector listens to the events of one aggregate and keeps a projection of that aggregate's data. It is the most common projector. The SKILL.md "Basic structure" example is the full pattern: `ProductInventoryProjector` builds `ProductInventory` records from `Product` events.

## The projection

A projection must declare at least one field with `identifier=True`, as `ProductInventory.product_id` does. Without one, registration raises ``IncorrectUsageError: Projection `NoId` needs to have at least one identifier``.

## How aggregates derive stream categories

When you pass `aggregates=[Product]`, Protean derives the stream category from `Product.meta_.stream_category`. This is equivalent to:

```python
# fragment
@domain.projector(
    projector_for=ProductInventory,
    stream_categories=[Product.meta_.stream_category],
)
```

Prefer `aggregates` unless you need to name the streams yourself.

## Complete example

See [projector_single_aggregate.py](../assets/projector_single_aggregate.py) for a complete, runnable example.

## Related

- [Cross-Aggregate Projector](cross-aggregate.md): Projector listening to multiple aggregates
- [Multiple Projectors](multiple-projectors.md): Multiple projectors for the same events
- [Anti-patterns](anti-patterns.md): Common mistakes to avoid
- `projection`: Defining projections
- `event`: Events that projectors consume
