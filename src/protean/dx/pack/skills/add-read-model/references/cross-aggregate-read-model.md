# Cross-Aggregate Read Model

A cross-aggregate read model combines data from two or more aggregates into a single queryable projection. This is essential when the UI needs to display data that spans aggregate boundaries.

## When to use

- A dashboard or report needs data from multiple aggregates
- The query combines information that lives in different bounded contexts
- You need a denormalized view that joins aggregate data at query time

## How it works

1. Multiple aggregates raise events independently
2. A single projector listens to events from all contributing aggregates
3. The projector builds and updates one projection from all event sources

```python
@domain.projector(
    projector_for=CustomerOrderSummary,
    aggregates=[Customer, Order],
)
class CustomerOrderSummaryProjector:
    @on(CustomerRegistered)
    def on_customer_registered(self, event):
        # Initialize the projection record from Customer data
        ...

    @on(OrderPlaced)
    def on_order_placed(self, event):
        # Update the projection record with Order data
        ...
```

## Key considerations

### Event ordering

Events from different aggregates may arrive in any order. Design your projector to handle:

- **Initialize first, update later**: The initialization event (e.g., `CustomerRegistered`) should create the projection record. Subsequent events update it.
- **Missing records**: If an update event arrives before the initialization event, you may need to handle the missing record gracefully.

### Identifier mapping

The projection identifier is typically the "owner" aggregate's ID. Events from other aggregates need a foreign key to locate the correct projection record.

```python
class CustomerOrderSummary:
    customer_id: Identifier(identifier=True)  # Customer's ID
    ...

class OrderPlaced:
    customer_id: Identifier(required=True)  # Links to the projection
    ...
```

### Data consistency

Cross-aggregate projections are eventually consistent. The projection may briefly show stale data when events from different aggregates are processed at different times.

## Projector configuration

Use the `aggregates` parameter to list all aggregate classes:

```python
@domain.projector(
    projector_for=MyProjection,
    aggregates=[AggregateA, AggregateB, AggregateC],
)
```

Alternatively, use `stream_categories` for explicit stream names:

```python
@domain.projector(
    projector_for=MyProjection,
    stream_categories=["customer", "order"],
)
```

## Complete example

See [read_model_cross_aggregate.py](../assets/read_model_cross_aggregate.py) for a complete runnable example combining Customer and Order data into a CustomerOrderSummary projection.
