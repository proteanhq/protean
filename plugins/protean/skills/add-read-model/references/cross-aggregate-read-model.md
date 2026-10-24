# Cross-Aggregate Read Model

A cross-aggregate read model combines data from two or more aggregates into a single queryable projection, for a UI that displays data spanning aggregate boundaries.

## When to use

- A dashboard or report needs data from multiple aggregates
- You need a denormalized view that joins aggregate data before the query runs, so the query reads one record

## How it works

Each aggregate raises its own events, and one projector listens to all of them. Start with the two aggregates, their events and the projection:

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
- **Missing records**: If an update event arrives before the initialization event, `repo.get` in `on_order_placed` raises `ObjectNotFoundError`. Create the record there when it is missing.

### Redelivered events

Redelivery breaks this projector the way it breaks the cross-aggregate projector in SKILL.md: a redelivered `OrderPlaced` counts the order again, and a redelivered `CustomerRegistered` fails because the record already exists. The fix and its limits (an upsert for the create handler, `idempotent=True` for the running totals) are under "Redelivered events" in SKILL.md.

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

The `aggregates` parameter lists every contributing aggregate class, as above. Alternatively, use `stream_categories` for explicit stream names. Derive each name from its aggregate. The real category is qualified by the domain name (`<domain>::customer`), so a bare `"customer"` matches no stream.

```python
# fragment
@domain.projector(
    projector_for=MyProjection,
    stream_categories=[Customer.meta_.stream_category, Order.meta_.stream_category],
)
```

## Reading the model back

A query handler reads through `domain.view_for`, as in SKILL.md Step 6:

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

## Complete example

See [read_model_cross_aggregate.py](../assets/read_model_cross_aggregate.py) for a complete runnable example combining Customer and Order data into a CustomerOrderSummary projection.
