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

Start with the two aggregates, their events and the projection:

```python
@domain.aggregate
class Customer:
    name: String(required=True)

    @classmethod
    def register(cls, name):
        customer = cls(name=name)
        customer.raise_(CustomerRegistered(customer_id=customer.id, name=name))
        return customer

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total_amount: Float(required=True)

    @classmethod
    def place(cls, customer_id, total_amount):
        order = cls(customer_id=customer_id, total_amount=total_amount)
        order.raise_(OrderPlaced(
            order_id=order.id, customer_id=customer_id, total_amount=total_amount
        ))
        return order

@domain.event(part_of=Customer)
class CustomerRegistered:
    customer_id: Identifier(required=True)
    name: String(required=True)

@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total_amount: Float(required=True)

@domain.projection
class CustomerOrderSummary:
    customer_id: Identifier(identifier=True)
    customer_name: String(max_length=100)
    order_count: Integer(default=0)
    total_spent: Float(default=0.0)
```

The projector listens to both aggregates:

```python
from protean.core.projector import on

@domain.projector(
    projector_for=CustomerOrderSummary,
    aggregates=[Customer, Order],
)
class CustomerOrderSummaryProjector:
    @on(CustomerRegistered)
    def on_customer_registered(self, event):
        # Initialize the projection record from Customer data
        summary = CustomerOrderSummary(
            customer_id=event.customer_id, customer_name=event.name
        )
        domain.repository_for(CustomerOrderSummary).add(summary)

    @on(OrderPlaced)
    def on_order_placed(self, event):
        # Update the projection record with Order data
        repo = domain.repository_for(CustomerOrderSummary)
        summary = repo.get(event.customer_id)
        summary.order_count += 1
        summary.total_spent += event.total_amount
        repo.add(summary)
```

## Key considerations

### Event ordering

Events from different aggregates may arrive in any order. Design your projector to handle:

- **Initialize first, update later**: The initialization event (e.g., `CustomerRegistered`) should create the projection record. Subsequent events update it.
- **Missing records**: If an update event arrives before the initialization event, you may need to handle the missing record gracefully.

### Redelivered events

An event can be delivered more than once. As written, this projector counts the order again when `OrderPlaced` is redelivered, and a redelivered `CustomerRegistered` fails because the record already exists. Writing `on_customer_registered` as an upsert (get the record, create it only if missing) fixes the second case. An upsert does not fix the first: adding to a count or a total is not safe to repeat, so set `idempotent=True` on the projector to have the framework skip an event it has already handled. That option is exactly-once only on a transactional database provider and does nothing for a cache-backed projection (see the `idempotent` option in [projector](../../projector/SKILL.md)).

### Identifier mapping

The projection identifier is typically the "owner" aggregate's ID. Events from other aggregates need a foreign key to locate the correct projection record.

```python
# fragment
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
# fragment
@domain.projector(
    projector_for=MyProjection,
    aggregates=[AggregateA, AggregateB, AggregateC],
)
```

Alternatively, use `stream_categories` for explicit stream names. Derive each name from its aggregate. The real category is qualified by the domain name (`<domain>::customer`), so a bare `"customer"` matches no stream.

```python
# fragment
@domain.projector(
    projector_for=MyProjection,
    stream_categories=[Customer.meta_.stream_category, Order.meta_.stream_category],
)
```

## Reading the model back

Answer reads with a query and a query handler. The handler reads through `domain.view_for`, which is read-only.

```python
from protean import current_domain, read

@domain.query(part_of=CustomerOrderSummary)
class GetCustomerOrderSummary:
    customer_id: Identifier(required=True)

@domain.query_handler(part_of=CustomerOrderSummary)
class CustomerOrderSummaryQueryHandler:
    @read(GetCustomerOrderSummary)
    def get_summary(self, query: GetCustomerOrderSummary):
        return current_domain.view_for(CustomerOrderSummary).get(query.customer_id)

domain.config["event_processing"] = "sync"  # run the projector right away
domain.init(traverse=False)

with domain.domain_context():
    customer = Customer.register(name="Ada")
    domain.repository_for(Customer).add(customer)

    order = Order.place(customer_id=customer.id, total_amount=120.0)
    domain.repository_for(Order).add(order)

    summary = domain.dispatch(GetCustomerOrderSummary(customer_id=customer.id))
    assert (summary.customer_name, summary.order_count, summary.total_spent) == (
        "Ada",
        1,
        120.0,
    )
```

`view_for(...).get()` raises `ObjectNotFoundError` when no record has that id. With asynchronous event processing, that includes a read made right after the write, before the projector has run.

## Complete example

See [read_model_cross_aggregate.py](../assets/read_model_cross_aggregate.py) for a complete runnable example combining Customer and Order data into a CustomerOrderSummary projection.
