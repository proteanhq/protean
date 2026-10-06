# Fact Events

Fact events contain the complete state of an aggregate at a specific point in time. They enable the Event-carried State Transfer pattern, where consumers receive all necessary information without needing to track history or query for additional data.

## Overview

Unlike delta events that capture incremental changes, fact events provide a complete snapshot of aggregate state. This simplifies consumption for external systems that don't need to maintain event history or reconstruct state from multiple events.

**When to use fact events:**
- Communicating with external bounded contexts or systems
- When consumers shouldn't build state from multiple delta events
- Providing read models to external APIs or services
- Simplifying consumer logic (no need to track event history)

## Code

The complete implementation is in [assets/event_fact.py](../assets/event_fact.py).

Key highlights:
- Generated with `@domain.aggregate(fact_events=True)`, no event class to write
- Contains complete aggregate state
- Enables Event-carried State Transfer pattern
- Simplifies consumer logic
- Larger payload but simpler consumption

## Event-carried State Transfer Pattern

The Event-carried State Transfer pattern means that events carry enough information for consumers to maintain their own local copy of data without needing to query back to the source system.

### Benefits

1. **Reduced coupling** - Consumers don't need to call back to the producer
2. **Improved performance** - All data is in the event, no additional queries needed
3. **Simplified consumer logic** - No need to track and replay multiple events
4. **Better availability** - Consumers work even if producer is down

### Trade-offs

1. **Larger events** - More data in each event
2. **Data duplication** - Same data sent to multiple consumers
3. **Eventual consistency** - Consumers may temporarily have stale data
4. **Schema evolution** - Changes affect all consumers

## Characteristics

### 1. Complete State

A fact event carries every field of the aggregate. You do not declare the event class. Set `fact_events=True` on the aggregate, and Protean generates an `<Aggregate>FactEvent` class from the aggregate's fields during `domain.init()`. For `Customer`, the class is `CustomerFactEvent`.

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.value_object
class Address:
    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)

@domain.aggregate(fact_events=True)
class Customer:
    email: String(required=True, max_length=255)
    full_name: String(required=True, max_length=200)
    phone: String(max_length=20)
    primary_address = ValueObject(Address)
    status: String(default="active")
    account_type: String(default="standard")
    loyalty_tier: String(max_length=50)
    preferences: Dict()

    def upgrade(self, tier):
        self.account_type = "premium"
        self.loyalty_tier = tier
```

### 2. Self-contained Information

Consumers read the whole state from one event. The repository writes the fact event when it saves the aggregate. It goes to the `<stream_category>-fact-<id>` stream:

```python
domain.init(traverse=False)
with domain.domain_context():
    customer = Customer(
        email="john.doe@example.com",
        full_name="John Doe",
        primary_address=Address(
            street="456 Market St",
            city="San Francisco",
            postal_code="94102",
            country="USA",
        ),
    )
    domain.repository_for(Customer).add(customer)

    stream = f"{Customer.meta_.stream_category}-fact-{customer.id}"
    fact = domain.event_store.store.read(stream)[-1].to_domain_object()
    print(type(fact).__name__)  # CustomerFactEvent
    print(fact.full_name, fact.primary_address.city)  # John Doe San Francisco
```

## When to Use Fact Events

### Use Fact Events When:

1. **External consumers** - Other bounded contexts or systems need current state
2. **Simplified consumption** - Consumers shouldn't need to maintain event history
3. **Integration events** - Publishing to external systems or APIs

### Use Delta Events When:

1. **Event sourcing** - Reconstructing state by replaying events
2. **Internal projections** - Building custom read models from event stream
3. **Audit trail** - Detailed change history required
4. **Minimal data transfer** - Bandwidth or storage constraints

### Hybrid Approach

Many systems use both:
- **Delta events** for internal event sourcing and projections
- **Fact events** for external communication and integration

The aggregate raises delta events by hand and also turns on `fact_events=True`. Each save writes both:

```python
from datetime import datetime, timezone

# Internal delta events
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)

@domain.event(part_of="Order")
class OrderShipped:
    order_id: String(required=True, identifier=True)
    shipped_at: DateTime(required=True)

# External consumers read the generated OrderFactEvent
@domain.aggregate(fact_events=True)
class Order:
    customer_id: String(required=True)
    status: String(default="draft")
    total = ValueObject(Money)
    shipping_address = ValueObject(Address)
    placed_at: DateTime()
    shipped_at: DateTime()

    def place(self):
        self.status = "placed"
        self.placed_at = datetime.now(timezone.utc)
        self.raise_(OrderPlaced(
            order_id=self.id,
            customer_id=self.customer_id,
            placed_at=self.placed_at,
        ))

    def ship(self):
        self.status = "shipped"
        self.shipped_at = datetime.now(timezone.utc)
        self.raise_(OrderShipped(order_id=self.id, shipped_at=self.shipped_at))
```

## Examples

### E-Commerce Order

The delta events go to the order's own stream. The fact events go to the fact stream, one per save:

```python
domain.init(traverse=False)
with domain.domain_context():
    repo = domain.repository_for(Order)
    order = Order(customer_id="CUST-123", total=Money(amount=99.99))
    order.place()
    repo.add(order)  # writes OrderPlaced and the first OrderFactEvent

    order = repo.get(order.id)
    order.ship()
    repo.add(order)  # writes OrderShipped and a second OrderFactEvent

    store = domain.event_store.store
    category = Order.meta_.stream_category
    delta = [type(m.to_domain_object()).__name__ for m in store.read(f"{category}-{order.id}")]
    facts = [m.to_domain_object().status for m in store.read(f"{category}-fact-{order.id}")]
    print(delta)  # ['OrderPlaced', 'OrderShipped']
    print(facts)  # ['placed', 'shipped']
```

### Customer Profile Updates

Every save that changes the customer adds one fact event. The last one holds the current state:

```python
with domain.domain_context():
    repo = domain.repository_for(Customer)
    customer = Customer(email="jane.roe@example.com", full_name="Jane Roe")
    repo.add(customer)

    customer = repo.get(customer.id)
    customer.upgrade("gold")
    repo.add(customer)

    stream = f"{Customer.meta_.stream_category}-fact-{customer.id}"
    messages = domain.event_store.store.read(stream)
    latest = messages[-1].to_domain_object()
    print(len(messages), type(latest).__name__)  # 2 CustomerFactEvent
    print(latest.account_type, latest.loyalty_tier)  # premium gold
```

## When Fact Events Are Written

You never raise a fact event yourself. The repository writes one when it saves an aggregate that is new or has changed. Saving an unchanged aggregate writes nothing:

```python
with domain.domain_context():
    repo = domain.repository_for(Customer)
    customer = Customer(email="sam.lee@example.com", full_name="Sam Lee")
    repo.add(customer)

    customer = repo.get(customer.id)
    repo.add(customer)  # no changes, so no new fact event

    stream = f"{Customer.meta_.stream_category}-fact-{customer.id}"
    print(len(domain.event_store.store.read(stream)))  # 1
```

## Best Practices

1. **Let Protean generate the event** - Use `fact_events=True` instead of writing a snapshot event by hand
2. **Version carefully** - The event's fields follow the aggregate's fields, so changing the aggregate changes what every consumer receives
3. **Read the timestamp from metadata** - `fact._metadata.headers.time` records when the save happened
4. **Don't over-use** - Fact events are heavier than delta events
5. **Document consumer expectations** - What data consumers should use

## Related

- [Delta Events](./delta-events.md) - Incremental state changes
- [With Value Objects](./with-value-objects.md) - Using value objects in events
- [Raising Events](./raising-events.md) - How to emit events from aggregates
