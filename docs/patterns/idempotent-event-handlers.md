# Idempotent Event Handlers

## The Problem

An event handler processes `OrderPlaced` events and awards loyalty points:

```python
# fragment
@domain.event_handler(part_of=Order)
class LoyaltyEventHandler:
    @handle(OrderPlaced)
    def award_points(self, event: OrderPlaced):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(event.customer_id)
        loyalty.add_points(int(event.total))
        repo.add(loyalty)
```

In production, the Protean server processes events from the event store via
subscriptions. The subscription tracks its position in the stream, advancing as
events are processed. But the server crashes between processing the event and
persisting the updated position. On restart, the subscription resumes from its
last saved position, and delivers the same `OrderPlaced` event again.

The handler runs a second time. The customer gets double loyalty points.

This is not a rare edge case. It happens routinely in distributed systems:

- **Server restart during processing**: The event was handled, the aggregate
  was persisted, but the subscription position wasn't updated before the crash.

- **Broker redelivery**: The message broker delivered the event, but the
  consumer didn't acknowledge it before disconnecting. The broker redelivers.

- **Subscription replay**: A subscription is restarted from an earlier position
  for debugging, migration, or recovery.

- **Network partitions**: The handler commits to the database but the
  acknowledgment to the event store is lost. The event is redelivered.

- **Competing consumers**: In a multi-instance deployment, two instances
  briefly process the same event before coordination kicks in.

Unlike commands (covered in [Command Idempotency](command-idempotency.md)),
events represent **facts that already happened**. You cannot reject an event or
return an error to its producer. The Order was placed. The handler must deal
with it, potentially more than once.

---

## The Pattern

Design every event handler to produce the **same result** whether it processes
an event once or multiple times. The aggregate's state after two deliveries
should be identical to its state after one.

This is achieved through one of three strategies:

1. **Naturally idempotent operations**: Operations that produce the same
   result regardless of repetition (set-based, not additive).
2. **Deduplication**: Detecting and skipping duplicate deliveries.
3. **Upsert instead of insert**: Using database semantics that handle
   duplicates gracefully.

The examples on this page react to events from an `Order` aggregate:

```python
--8<-- "patterns/idempotent-event-handlers/001.py:order"
```

Each handler that reacts to `OrderPlaced`, `OrderPaid` or `OrderShipped` is
declared with `part_of=Order`, even when it changes another aggregate. A
handler listens to the stream of the aggregate it is part of, so a handler
declared with `part_of=CustomerLoyalty` would never receive `OrderPlaced`.

---

## Events vs Commands: Why Handlers Differ

The [Command Idempotency](command-idempotency.md) pattern covers framework-level
deduplication for commands using idempotency keys and Redis-backed caches.
Event handlers have different characteristics:

| Aspect | Commands | Events |
|--------|----------|--------|
| Semantics | Intent to change | Fact that occurred |
| Can be rejected? | Yes | No (it already happened) |
| Idempotency key | Caller-provided | Not applicable |
| Framework dedup | Redis-backed cache (Layers 1-2) | Subscription position; projectors can opt into `idempotent=True` |
| Handler responsibility | Defense-in-depth | Primary defense |

Because events don't carry caller-provided idempotency keys, the handler itself
is the primary defense against duplicate processing. The subscription's position
tracking provides some protection, but it's not sufficient (position updates
are periodic, not per-message). A projector can opt into
[`idempotent=True`](../guides/consume-state/projectors.md), which records a
marker per event and skips a redelivered one. Event handlers have no such
option.

---

## Strategy 1: Naturally Idempotent Operations

The simplest and most reliable approach. If the handler's operation produces the
same result whether executed once or ten times, duplicates are harmless.

### Set-Based Operations

Operations that **set** state rather than **add** to it are naturally
idempotent:

```python
--8<-- "patterns/idempotent-event-handlers/001.py:set_based"
```

Setting `status = "shipped"` ten times leaves the status at "shipped". There's
no accumulation, no duplication, no corruption.

**More naturally idempotent patterns:**

- Replacing a value: `user.email = event.new_email`
- Overwriting a flag: `order.is_paid = True`
- Assigning a reference: `task.assignee_id = event.user_id`
- Replacing a value object: `account.address = Address(...)`

### When to Prefer Set-Based Design

If you can design your event handler to use set-based operations instead of
additive ones, always do so. It eliminates the need for deduplication
entirely.

For example, instead of incrementing a counter:

```python
# fragment
# Additive (NOT idempotent)
def on_order_placed(self, event: OrderPlaced):
    stats.order_count += 1
    stats.total_revenue += event.total
```

Consider maintaining the full state. `record_order` keeps the orders keyed by
order ID and recalculates the totals from them, so recording the same order
twice changes nothing:

```python
--8<-- "patterns/idempotent-event-handlers/001.py:order_stats"
```

---

## Strategy 2: Deduplication

When the operation is inherently additive (incrementing counters, appending
to lists, creating new records), you need explicit deduplication.

### Check-Before-Act

The simplest deduplication: check whether the event has already been processed
before processing it.

```python
--8<-- "patterns/idempotent-event-handlers/001.py:check_before_act"
```

The `Inventory` aggregate tracks which orders have already reserved stock.
If the same `OrderPlaced` event arrives twice, the second delivery finds the
order ID already in `reserved_for_orders` and skips that item.

### Track Processed Event IDs

For handlers that process many event types, maintain a set of processed event
identifiers:

```python
--8<-- "patterns/idempotent-event-handlers/001.py:processed_events"
```

The handler assigns a new list instead of calling `append()` on the stored
one. Protean tracks a change to a `List` field when you assign it. An in-place
`append()` on its own is not seen as a change, so saving an aggregate whose only
change is the append does not store it.

The `processed_events` list is a bounded collection of recently processed
event IDs. For high-volume aggregates, prune entries older than a retention
window (e.g., keep only the last 1000 or entries from the last 24 hours).

### Use Event Sequence Numbers

When a handler reads events in event store order, the event's global position
can serve as a deduplication marker. The global position grows across the whole
store. The stream position (`event_store.position`) restarts at 0 for each
aggregate, so it cannot serve as one watermark shared by several aggregates:

```python
--8<-- "patterns/idempotent-event-handlers/001.py:global_position"
```

This is particularly useful for projectors that rebuild from an event stream
and need to track their position.

---

## Strategy 3: Upsert Operations

For handlers that create new records (like projections), use upsert semantics
to handle duplicates at the database level.

### Projector Upserts

Projectors are a common case where idempotency matters. When a projector
processes `OrderPlaced` to create an `OrderSummary` projection, a duplicate
delivery would try to create a second record with the same ID:

```python
--8<-- "patterns/idempotent-event-handlers/001.py:upsert_imports"
--8<-- "patterns/idempotent-event-handlers/001.py:upsert"
```

`repo.get()` raises `ObjectNotFoundError` when no record has the ID, so the
projector catches it to tell a first delivery from a repeat. This pattern
handles both first delivery and duplicate delivery. The result is the same
either way.

### Existence Guard

For handlers that create an aggregate, check whether one already exists for the
source of the event before creating it. `ShipmentRepository.find_by_order_id`
looks the shipment up by order ID and returns `None` when there is none:

```python
--8<-- "patterns/idempotent-event-handlers/001.py:existence_guard"
```

---

## Applying the Pattern: Worked Examples

### Example 1: Loyalty Points (Additive Operation)

Loyalty points are additive, awarding points twice doubles the reward. This
requires explicit deduplication.

```python
--8<-- "patterns/idempotent-event-handlers/002.py:loyalty"
```

The idempotency logic lives in the aggregate's `award_points` method, not
in the handler. The handler is thin. The aggregate checks its
`point_transactions` to detect duplicates.

### Example 2: Inventory Reservation (Cross-Aggregate Side Effect)

```python
--8<-- "patterns/idempotent-event-handlers/002.py:inventory_imports"
--8<-- "patterns/idempotent-event-handlers/002.py:inventory"
```

The `Reservation` entity within the `Inventory` aggregate acts as a
deduplication record. The `order_id` on each reservation uniquely identifies
the source event, making the operation idempotent.

### Example 3: Notification (External Side Effect)

External side effects (sending emails, calling APIs) require special care
because they cannot be rolled back:

```python
--8<-- "patterns/idempotent-event-handlers/002.py:notification_imports"
--8<-- "patterns/idempotent-event-handlers/002.py:notification"
```

Instead of sending the email directly (which can't be undone), the handler
creates a `Notification` record. If the event is redelivered, the handler finds
the existing notification and skips.

A separate process sends pending notifications and marks them as sent:

```python
--8<-- "patterns/idempotent-event-handlers/002.py:sender"
```

Each pending notification is sent once and then marked as sent, so a later run
of `send_pending_notifications` does not send it again.

---

## Event Handler vs Projector Idempotency

Projectors and event handlers have different idempotency characteristics:

### Projectors

Projectors maintain read-optimized projections. They're typically idempotent
by nature because they **set** the projection's state rather than accumulate it:

```python
--8<-- "patterns/idempotent-event-handlers/001.py:dashboard"
```

Each handler sets fields to specific values. Processing the same event twice
produces the same projection state.

### Event Handlers

Event handlers that modify domain aggregates need more care because aggregates
have business rules, invariants, and state machines:

```python
--8<-- "patterns/idempotent-event-handlers/001.py:account"
```

The key difference: projectors typically use set-based operations (naturally
idempotent), while event handlers often perform additive operations (require
explicit deduplication).

---

## When Perfect Idempotency Is Impractical

Some scenarios make perfect idempotency difficult:

### Time-Dependent Operations

If the handler's behavior depends on the current time, two executions at
different times may produce different results:

```python
# fragment
def on_order_placed(self, event: OrderPlaced):
    # This is NOT idempotent: running at different times changes the result
    if datetime.now() - event.placed_at > timedelta(hours=24):
        order.flag_as_delayed()
```

Mitigation: use the event's timestamp, not the current time, for time-dependent
decisions:

```python
# fragment
def on_order_placed(self, event: OrderPlaced):
    # Better: use event time, not wall clock
    if event.expected_delivery_date < event.placed_at + timedelta(hours=24):
        order.flag_as_delayed()
```

### External API Calls

If the handler calls an external API that's not idempotent, duplicate
processing produces duplicate external effects:

```python
# fragment
def on_order_placed(self, event: OrderPlaced):
    # NOT idempotent: sends duplicate SMS on redelivery
    sms_service.send(event.customer_phone, "Your order is confirmed!")
```

Mitigation: use the status flag pattern (track whether the side effect
occurred) or the outbox pattern (create a record, send asynchronously with
deduplication).

---

## Signs Your Handler Isn't Idempotent

1. **Counter increments**: `stats.count += 1` is not idempotent.

2. **List appends without checking**: `items.append(new_item)` without
   checking if the item is already present.

3. **Creating records without existence checks**: `repo.add(new_record)`
   without checking if a record for this event already exists.

4. **Direct external API calls**: Sending emails, SMS, or API requests
   without deduplication.

5. **Generating new identifiers**: If the handler creates a new aggregate
   with `Auto(identifier=True)`, a duplicate delivery creates a second
   aggregate with a different ID.

---

## Summary

| Strategy | When to Use | Complexity | Robustness |
|----------|-------------|------------|------------|
| Set-based operations | Handler sets state, doesn't accumulate | Low | High |
| Check-before-act | Additive operations, moderate volume | Medium | High |
| Processed event tracking | Multiple event types, need audit trail | Medium | High |
| Global position tracking | Handlers that read events in store order | Medium | Medium |
| Upsert | Creating or updating projections | Low | High |
| Status flags | External side effects | Medium | High |

Every event handler must produce the same result whether it processes an event
once or multiple times. Prefer naturally idempotent operations. When that's not
possible, deduplicate explicitly. The handler, not the framework, is the
primary defense against duplicate events.

---

!!! tip "Related reading"
    **Concepts:**

    - [Event Handlers](../concepts/building-blocks/event-handlers.md): How event handlers consume and process events.

    **Guides:**

    - [Event Handlers](../guides/consume-state/event-handlers.md): Defining handlers, configuration, and error handling.
