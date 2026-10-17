# Design Events for Consumers

## The Problem

A developer raises a domain event when an order is placed:

```python
# fragment
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
```

The event carries just the order ID. Downstream, an event handler needs to
send a confirmation email:

```python
# fragment
@domain.event_handler(part_of=Notification)
class NotificationEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def send_confirmation(self, event: OrderPlaced):
        # Need customer email, name, items, total...
        # But the event only has order_id.
        repo = current_domain.repository_for(Order)
        order = repo.get(event.order_id)

        # Now send the email using order details
        send_email(
            to=order.customer_email,  # Wait, Order doesn't have email...
            subject=f"Order {order.order_id} confirmed",
            body=format_order_details(order),
        )
```

The handler must load the Order aggregate to get the data it needs. But the
Notification handler shouldn't know about the Order aggregate at all, it's in a
different bounded context. Now a projector also needs the data:

```python
# fragment
@domain.projector(projector_for=OrderSummaryProjection, aggregates=[Order])
class OrderSummaryProjector(BaseProjector):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Again, need to load the Order to get details
        repo = current_domain.repository_for(Order)
        order = repo.get(event.order_id)

        projection = OrderSummaryProjection(
            order_id=order.order_id,
            customer_name=order.customer_name,  # Need customer data too
            total=order.total,
            item_count=len(order.items),
        )
        current_domain.repository_for(OrderSummaryProjection).add(projection)
```

Every consumer must load the aggregate. This creates a cascade of problems:

- **Coupling through queries**: Every event consumer depends on the Order
  aggregate's structure. If Order's fields change, every consumer breaks.

- **Performance degradation**: Each consumer triggers a separate database
  query to load the same aggregate. With five consumers, a single event causes
  five aggregate loads.

- **Cross-aggregate data access**: The notification handler needs the customer's
  email, which lives on the Customer aggregate. Now it needs to load *two*
  aggregates (Order and Customer) to process one event.

- **Event sourcing incompatibility**: In an event-sourced system, the aggregate's
  current state may have advanced past the state at the time the event was raised.
  Loading the current aggregate gives you *today's* data, not the data at event
  time.

- **Broken in async processing**: When events are processed asynchronously (as
  they should be), the aggregate may have been modified between when the event
  was raised and when the handler runs. The handler loads stale or inconsistent
  data.

The root cause: **events carry references instead of data, forcing consumers
to query back to the source**.

---

## The Pattern

Design events to carry **enough context for consumers to act independently**,
without querying back to the source aggregate.

```
Thin event (anti-pattern):
  OrderPlaced { order_id }
  → Consumer loads Order to get details
  → Consumer loads Customer to get email
  → Coupled, slow, fragile

Rich event (pattern):
  OrderPlaced { order_id, customer_id, customer_name, customer_email,
                items, total, placed_at }
  → Consumer has everything it needs
  → No queries, no coupling, no fragility
```

This doesn't mean events should contain the entire aggregate. It means events
should contain the data that **consumers need to do their job**.

### The Litmus Test

For every event you design, ask:

> "Can every consumer of this event process it without loading any other
> aggregate?"

If the answer is no, the event is too thin. Add the data that consumers need.

---

## Delta Events vs Fact Events

Protean supports two styles of events, and the choice affects how you design
event payloads.

### Delta Events: What Changed

Delta events capture **the specific change** that occurred. They carry the data
relevant to that particular state transition:

```python
--8<-- "patterns/design-events-for-consumers/001.py:delta_events"
```

Delta events are **specific and intentional**. Each event type carries exactly
the data relevant to that operation. This is the primary style for
hand-crafted domain events.

**When to use delta events:**

- When different consumers need different data for different events
- When you want precise, minimal event payloads
- When events represent meaningful business operations with specific data
- When using event sourcing (events are the source of truth)

### Fact Events: Complete State Snapshot

Fact events capture **the aggregate's complete state** after a change. Protean
can generate these automatically:

```python
--8<-- "patterns/design-events-for-consumers/002.py:fact_events"
```

With `fact_events=True`, Protean automatically raises a `OrderFactEvent` after
every successful persistence. The fact event contains the aggregate's complete
state as a snapshot.

**When to use fact events:**

- When consumers need the aggregate's full state (e.g., projections that
  mirror the aggregate)
- When you want to avoid hand-crafting event payloads for every state change
- When the projection essentially replicates the aggregate's structure
- For simple CQRS patterns where the read model mirrors the write model

**Trade-offs:**

| Aspect | Delta Events | Fact Events |
|--------|-------------|-------------|
| Payload size | Small (only what changed) | Large (full state) |
| Semantic meaning | High (named operations) | Low (generic "changed") |
| Consumer logic | Process the specific change | Replace the entire state |
| Event versioning | Must evolve each event type | Evolves with the aggregate |
| Event sourcing | Required | Not suitable (no operation semantics) |
| Protean support | Hand-crafted | Auto-generated with `fact_events=True` |

### Combining Both

You can use both delta and fact events on the same aggregate. Raise specific
delta events for meaningful operations, and let fact events provide a catch-all
for projections:

```python
--8<-- "patterns/design-events-for-consumers/003.py:combined"
```

Consumers that care about the specific operation listen for `OrderPlaced`.
Projections that just need the latest state listen for the fact event.

---

## Event Payload Design Principles

### 1. Include Identifiers for All Referenced Aggregates

Every aggregate that a consumer might need to correlate should have its
identity in the event:

```python
--8<-- "patterns/design-events-for-consumers/004.py:identifiers"
```

Even if a consumer doesn't need all of them, including identifiers is cheap
and enables future consumers without changing the event.

### 2. Carry Enough Context for Consumers to Act Without Querying Back

Think about what each consumer does with this event:

```python
--8<-- "patterns/design-events-for-consumers/005.py:consumer_fields"
```

### 3. Include Cross-Aggregate Data at Event Time

When the event references data from another aggregate, include a snapshot of
that data in the event. Don't force consumers to look it up:

```python
--8<-- "patterns/design-events-for-consumers/006.py:place"
```

The command carries the customer data because the caller (API layer) already
has it. The aggregate passes it into the event. No consumer needs to load the
Customer aggregate.

### 4. Don't Include Everything

Events should carry enough context, not the entire aggregate. Data that no
consumer needs should be omitted:

```python
# fragment
# Too much -- includes internal implementation details
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    internal_processing_flags: Dict()     # Internal detail, no consumer needs this
    database_version: Integer()           # Infrastructure concern
    raw_request_payload: Dict()           # API concern, not domain
```

The rule of thumb: include business data that consumers need, exclude
infrastructure details.

### 5. Events Are Immutable Contracts

Once an event is published and consumers depend on it, its fields become a
contract. Adding new fields is safe (existing consumers ignore them). Removing
or renaming fields is a breaking change.

Design events thoughtfully from the start, knowing that evolution is possible
but removal is painful.

---

## Projection-Driven Event Design

Projections are the most common event consumers. A practical approach to event
design is to **work backward from the projection**:

### Step 1: Define the Projection

```python
--8<-- "patterns/design-events-for-consumers/007.py:projection"
```

### Step 2: Identify What Data Each Event Must Carry

For the projector to build this projection:

- `OrderPlaced` must carry: order_id, customer_name, items (to count),
  total, placed_at
- `OrderShipped` must carry: order_id, shipped_at

### Step 3: Design Events to Satisfy the Projection

```python
--8<-- "patterns/design-events-for-consumers/007.py:events"
```

### Step 4: Write the Projector

```python
--8<-- "patterns/design-events-for-consumers/007.py:projector"
```

Every projector method works entirely from the event data. No aggregate loading,
no cross-boundary queries, no coupling.

---

## Handling Cross-Domain Events

When events cross domain boundaries (consumed by another bounded context),
the payload design becomes even more critical. The consuming domain should
never need to query back to the producing domain.

```python
--8<-- "patterns/design-events-for-consumers/008.py:published_event"
--8<-- "patterns/design-events-for-consumers/009.py:subscriber"
```

If the event doesn't carry enough data, the Fulfillment domain must call back
to the Order domain's API, creating runtime coupling between domains that
should be autonomous.

---

## When Thin Events Are Acceptable

### Internal Framework Events

Events used purely for internal framework mechanics (e.g., triggering a
projection rebuild) can be thin:

```python
--8<-- "patterns/design-events-for-consumers/010.py:internal_trigger"
```

### Events with Fact Event Fallback

If you use `fact_events=True` on the aggregate, delta events can be thinner
because consumers that need full state can listen for the fact event instead:

```python
--8<-- "patterns/design-events-for-consumers/010.py:thin_delta"
```

### Single-Consumer Events

If an event has exactly one consumer and that consumer is in the same bounded
context, a thin event with an aggregate lookup is a pragmatic choice. But
consider that consumers may be added later.

---

## Anti-Patterns

### The "Just Load It" Event

```python
# fragment
# Anti-pattern: event that's useless without a query
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    # That's it. Every consumer must load the Order aggregate.
```

### The event that carries everything

```python
# fragment
# Anti-pattern: event with every field from the aggregate
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_name: String()
    customer_email: String()
    customer_phone: String()
    customer_address: Dict()
    items: List()
    item_count: Integer()          # Derivable from items
    total: Float()
    subtotal: Float()              # Derivable from items
    tax: Float()                   # Derivable from total - subtotal
    discount: Float()
    coupon_code: String()
    internal_notes: String()       # No consumer needs this
    created_by_admin: Boolean()    # Internal flag
    # ... 20 more fields
```

Include what consumers need, not everything the aggregate has. Derivable
fields (item_count from items, subtotal from items) are noise.

### Exposing Internal State

```python
# fragment
# Anti-pattern: leaking implementation details
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    state_machine_state: String()   # Internal implementation detail
    _version: Integer()             # Framework concern
    retry_count: Integer()          # Infrastructure concern
```

Events are part of your domain's public contract. They should contain
business-meaningful data, not implementation details.

---

## Summary

| Aspect | Thin Events | Rich Events |
|--------|------------|-------------|
| Consumer independence | Low (must query back) | High (self-contained) |
| Cross-domain coupling | High (consumers depend on source) | Low (consumers are autonomous) |
| Performance | Poor (N queries per event) | Good (no extra queries) |
| Event sourcing fit | Poor (state at event time lost) | Good (snapshot at event time) |
| Payload size | Small | Larger |
| Design effort | Low (just the ID) | Higher (think about consumers) |
| Evolution cost | Low (nothing to change) | Higher (more fields to maintain) |

Design events so that every consumer can process them independently. Include
enough context for consumers to act without querying back to the source
aggregate. Work backward from the projection to determine what data each event
must carry.

---

!!! tip "Related reading"
    **Concepts:**

    - [Events](../concepts/building-blocks/events.md): Domain events and their role in the system.
    - [Projections](../concepts/building-blocks/projections.md): Read-optimized views built from events.

    **Guides:**

    - [Events](../guides/domain-definition/events.md): Defining events, structure, and metadata.
    - [Raising Events](../guides/domain-behavior/raising-events.md): Raising and dispatching events from aggregates.
    - [Projections](../guides/consume-state/projections.md): Building read models with projectors.
