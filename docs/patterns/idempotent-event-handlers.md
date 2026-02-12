# Idempotent Event Handlers

## The Problem

An event handler processes `OrderPlaced` events and awards loyalty points:

```python
@domain.event_handler(part_of=CustomerLoyalty)
class LoyaltyEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def award_points(self, event: OrderPlaced):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(event.customer_id)
        loyalty.add_points(int(event.total))
        repo.add(loyalty)
```

In production, the Protean server processes events from the event store via
subscriptions. The subscription tracks its position in the stream, advancing
as events are processed. But the server crashes between processing the event
and persisting the updated position. On restart, the subscription resumes from
its last saved position -- and delivers the same `OrderPlaced` event again.

The handler runs a second time. The customer gets double loyalty points.

This is not a rare edge case. It happens routinely in distributed systems:

- **Server restart during processing.** The event was handled, the aggregate
  was persisted, but the subscription position wasn't updated before the crash.

- **Broker redelivery.** The message broker delivered the event, but the
  consumer didn't acknowledge it before disconnecting. The broker redelivers.

- **Subscription replay.** A subscription is restarted from an earlier position
  for debugging, migration, or recovery.

- **Network partitions.** The handler commits to the database but the
  acknowledgment to the event store is lost. The event is redelivered.

- **Competing consumers.** In a multi-instance deployment, two instances
  briefly process the same event before coordination kicks in.

Unlike commands (covered in [Command Idempotency](command-idempotency.md)),
events represent **facts that already happened**. You cannot reject an event or
return an error to its producer. The Order was placed. The handler must deal
with it -- potentially more than once.

---

## The Pattern

Design every event handler to produce the **same result** whether it processes
an event once or multiple times. The aggregate's state after two deliveries
should be identical to its state after one.

This is achieved through one of three strategies:

1. **Naturally idempotent operations** -- operations that produce the same
   result regardless of repetition (set-based, not additive).
2. **Deduplication** -- detecting and skipping duplicate deliveries.
3. **Upsert instead of insert** -- using database semantics that handle
   duplicates gracefully.

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
| Framework dedup | Redis-backed cache (Layers 1-2) | Subscription position only |
| Handler responsibility | Defense-in-depth | Primary defense |

Because events don't carry caller-provided idempotency keys, the handler itself
is the primary defense against duplicate processing. The subscription's position
tracking provides some protection, but it's not sufficient (position updates
are periodic, not per-message).

---

## Strategy 1: Naturally Idempotent Operations

The simplest and most robust approach. If the handler's operation produces the
same result whether executed once or ten times, duplicates are harmless.

### Set-Based Operations

Operations that **set** state rather than **add** to it are naturally idempotent:

```python
@domain.event_handler(part_of=OrderStatus)
class OrderStatusEventHandler(BaseEventHandler):

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderStatus)
        status = repo.get(event.order_id)
        # Setting status to "shipped" is idempotent
        # Doing it twice produces the same result
        status.status = "shipped"
        status.shipped_at = event.shipped_at
        status.tracking_number = event.tracking_number
        repo.add(status)
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
# Additive (NOT idempotent)
def on_order_placed(self, event: OrderPlaced):
    stats.order_count += 1
    stats.total_revenue += event.total
```

Consider maintaining the full state:

```python
# Set-based (idempotent)
def on_order_placed(self, event: OrderPlaced):
    # Recalculate from the projection's stored orders
    stats.record_order(event.order_id, event.total)
    # record_order uses a set: adding the same order_id twice is a no-op
```

---

## Strategy 2: Deduplication

When the operation is inherently additive (incrementing counters, appending
to lists, creating new records), you need explicit deduplication.

### Check-Before-Act

The simplest deduplication: check whether the event has already been processed
before processing it.

```python
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)

        for item in event.items:
            inventory = repo.get(item["product_id"])

            # Check if this event's reservation was already applied
            if event.order_id in inventory.reserved_for_orders:
                continue  # Already processed, skip

            inventory.reserve(
                quantity=item["quantity"],
                order_id=event.order_id,
            )
            repo.add(inventory)
```

The `Inventory` aggregate tracks which orders have already reserved stock.
If the same `OrderPlaced` event arrives twice, the second delivery finds the
order ID already in the set and skips.

### Track Processed Event IDs

For handlers that process many event types, maintain a set of processed event
identifiers:

```python
@domain.event_handler(part_of=CustomerLoyalty)
class LoyaltyEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def award_points(self, event: OrderPlaced):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(event.customer_id)

        # Use the event's unique ID for deduplication
        event_id = event._metadata.headers.id
        if event_id in loyalty.processed_events:
            return  # Already processed

        loyalty.add_points(int(event.total))
        loyalty.processed_events.append(event_id)
        repo.add(loyalty)
```

The `processed_events` list is a bounded collection of recently processed
event IDs. For high-volume aggregates, prune entries older than a retention
window (e.g., keep only the last 1000 or entries from the last 24 hours).

### Use Event Sequence Numbers

When events come from a stream with guaranteed ordering, the stream position
itself can serve as a deduplication marker:

```python
@domain.event_handler(part_of=ProjectionState)
class ProjectionStateHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(ProjectionState)
        state = repo.get("order-projection")

        # Use stream position for deduplication
        event_position = event._metadata.headers.sequence
        if event_position <= state.last_processed_position:
            return  # Already processed or older

        # Process the event
        state.apply_order_placed(event)
        state.last_processed_position = event_position
        repo.add(state)
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
@domain.projector(part_of=OrderSummaryProjection)
class OrderSummaryProjector(BaseProjector):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderSummaryProjection)

        # Check if the projection already exists
        existing = repo.get(event.order_id)
        if existing:
            # Already created -- update instead of insert
            existing.customer_name = event.customer_name
            existing.total = event.total
            existing.placed_at = event.placed_at
            existing.status = "placed"
            repo.add(existing)
        else:
            # First time -- create
            projection = OrderSummaryProjection(
                order_id=event.order_id,
                customer_name=event.customer_name,
                status="placed",
                total=event.total,
                placed_at=event.placed_at,
            )
            repo.add(projection)
```

This pattern naturally handles both first delivery and duplicate delivery. The
result is the same either way.

### State Machine Guard

For handlers that trigger state transitions, use the aggregate's current state
as a guard:

```python
@domain.event_handler(part_of=Shipment)
class ShipmentEventHandler(BaseEventHandler):

    @handle(OrderPaid)
    def create_shipment(self, event: OrderPaid):
        repo = current_domain.repository_for(Shipment)

        # Check if a shipment already exists for this order
        existing = repo.find_by_order_id(event.order_id)
        if existing:
            return  # Shipment already created

        shipment = Shipment(
            order_id=event.order_id,
            customer_id=event.customer_id,
            items=event.items,
            status="pending",
        )
        repo.add(shipment)
```

---

## Applying the Pattern: Worked Examples

### Example 1: Loyalty Points (Additive Operation)

Loyalty points are additive -- awarding points twice doubles the reward.
This requires explicit deduplication.

```python
@domain.aggregate
class CustomerLoyalty:
    customer_id = Identifier(identifier=True)
    points = Integer(default=0)
    point_transactions = HasMany(PointTransaction)

    def award_points(self, order_id: str, amount: int) -> None:
        """Award loyalty points for an order, idempotently."""
        # Check if points were already awarded for this order
        for txn in self.point_transactions:
            if txn.source_id == order_id:
                return  # Already awarded

        self.points += amount
        self.point_transactions.add(PointTransaction(
            source_id=order_id,
            amount=amount,
            type="earned",
        ))


@domain.entity(part_of=CustomerLoyalty)
class PointTransaction:
    source_id = Identifier(required=True)
    amount = Integer(required=True)
    type = String(required=True)


@domain.event_handler(part_of=CustomerLoyalty)
class LoyaltyEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def award_points(self, event: OrderPlaced):
        repo = current_domain.repository_for(CustomerLoyalty)
        loyalty = repo.get(event.customer_id)
        # The aggregate method handles idempotency internally
        loyalty.award_points(
            order_id=event.order_id,
            amount=int(event.total),
        )
        repo.add(loyalty)
```

The idempotency logic lives in the aggregate's `award_points` method, not
in the handler. The handler is thin. The aggregate checks its
`point_transactions` to detect duplicates.

### Example 2: Inventory Reservation (Cross-Aggregate Side Effect)

```python
@domain.aggregate
class Inventory:
    product_id = Identifier(identifier=True)
    available_quantity = Integer(default=0)
    reservations = HasMany(Reservation)

    def reserve(self, order_id: str, quantity: int) -> None:
        """Reserve inventory for an order, idempotently."""
        # Check if already reserved for this order
        for reservation in self.reservations:
            if reservation.order_id == order_id:
                return  # Already reserved

        if self.available_quantity < quantity:
            raise ValidationError(
                {"quantity": [
                    f"Insufficient inventory. Available: {self.available_quantity}"
                ]}
            )

        self.available_quantity -= quantity
        self.reservations.add(Reservation(
            order_id=order_id,
            quantity=quantity,
        ))

        self.raise_(InventoryReserved(
            product_id=self.product_id,
            order_id=order_id,
            quantity=quantity,
        ))


@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(
                order_id=event.order_id,
                quantity=item["quantity"],
            )
            repo.add(inventory)
```

The `Reservation` entity within the `Inventory` aggregate acts as a
deduplication record. The `order_id` on each reservation uniquely identifies
the source event, making the operation idempotent.

### Example 3: Notification (External Side Effect)

External side effects (sending emails, calling APIs) require special care
because they cannot be rolled back:

```python
@domain.aggregate
class Notification:
    notification_id = Auto(identifier=True)
    recipient_id = Identifier(required=True)
    type = String(required=True)
    source_event_id = Identifier(required=True)
    status = String(default="pending")
    sent_at = DateTime()

    def mark_sent(self) -> None:
        self.status = "sent"
        self.sent_at = datetime.now(timezone.utc)


@domain.event_handler(part_of=Notification)
class NotificationEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def send_confirmation(self, event: OrderPlaced):
        repo = current_domain.repository_for(Notification)

        # Use event ID as the deduplication key
        event_id = event._metadata.headers.id
        existing = repo.find_by_source_event_id(event_id)

        if existing and existing.status == "sent":
            return  # Already sent

        if not existing:
            notification = Notification(
                recipient_id=event.customer_id,
                type="order_confirmation",
                source_event_id=event_id,
                status="pending",
            )
            repo.add(notification)

        # The actual sending happens via the outbox pattern
        # or a separate process that picks up pending notifications
```

Instead of sending the email directly (which can't be undone), the handler
creates a `Notification` record. A separate process sends pending notifications
and marks them as sent. If the event is redelivered, the handler finds the
existing notification and skips.

---

## Event Handler vs Projector Idempotency

Projectors and event handlers have different idempotency characteristics:

### Projectors

Projectors maintain read-optimized projections. They're typically idempotent
by nature because they **set** the projection's state rather than accumulate it:

```python
@domain.projector(part_of=OrderDashboardProjection)
class OrderDashboardProjector(BaseProjector):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderDashboardProjection)
        # Upsert pattern: create or update
        projection = repo.get(event.order_id)
        if not projection:
            projection = OrderDashboardProjection(order_id=event.order_id)

        projection.customer_name = event.customer_name
        projection.status = "placed"
        projection.total = event.total
        projection.placed_at = event.placed_at
        repo.add(projection)

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderDashboardProjection)
        projection = repo.get(event.order_id)
        if projection:
            projection.status = "shipped"
            projection.shipped_at = event.shipped_at
            repo.add(projection)
```

Each handler sets fields to specific values. Processing the same event twice
produces the same projection state.

### Event Handlers

Event handlers that modify domain aggregates need more care because aggregates
have business rules, invariants, and state machines:

```python
@domain.event_handler(part_of=Account)
class AccountEventHandler(BaseEventHandler):

    @handle(MoneyDebited)
    def credit_target(self, event: MoneyDebited):
        repo = current_domain.repository_for(Account)
        target = repo.get(event.target_account_id)

        # Must deduplicate because credit is additive
        if event.transfer_id in target.processed_transfers:
            return

        target.credit(event.amount)
        target.processed_transfers.append(event.transfer_id)
        repo.add(target)
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
def on_order_placed(self, event: OrderPlaced):
    # This is NOT idempotent -- running at different times changes the result
    if datetime.now() - event.placed_at > timedelta(hours=24):
        order.flag_as_delayed()
```

Mitigation: use the event's timestamp, not the current time, for time-dependent
decisions:

```python
def on_order_placed(self, event: OrderPlaced):
    # Better: use event time, not wall clock
    if event.expected_delivery_date < event.placed_at + timedelta(hours=24):
        order.flag_as_delayed()
```

### External API Calls

If the handler calls an external API that's not idempotent, duplicate
processing produces duplicate external effects:

```python
def on_order_placed(self, event: OrderPlaced):
    # NOT idempotent -- sends duplicate SMS on redelivery
    sms_service.send(event.customer_phone, "Your order is confirmed!")
```

Mitigation: use the status flag pattern (track whether the side effect
occurred) or the outbox pattern (create a record, send asynchronously with
deduplication).

---

## Signs Your Handler Isn't Idempotent

1. **Counter increments.** `stats.count += 1` is not idempotent.

2. **List appends without checking.** `items.append(new_item)` without
   checking if the item is already present.

3. **Creating records without existence checks.** `repo.add(new_record)`
   without checking if a record for this event already exists.

4. **Direct external API calls.** Sending emails, SMS, or API requests
   without deduplication.

5. **Generating new identifiers.** If the handler creates a new aggregate
   with `Auto(identifier=True)`, a duplicate delivery creates a second
   aggregate with a different ID.

---

## Summary

| Strategy | When to Use | Complexity | Robustness |
|----------|-------------|------------|------------|
| Set-based operations | Handler sets state, doesn't accumulate | Low | High |
| Check-before-act | Additive operations, moderate volume | Medium | High |
| Processed event tracking | Multiple event types, need audit trail | Medium | High |
| Stream position tracking | Single-stream projections | Medium | Medium |
| Upsert | Creating or updating projections | Low | High |
| Status flags | External side effects | Medium | High |

The principle: **every event handler must produce the same result whether it
processes an event once or multiple times. Prefer naturally idempotent
operations. When that's not possible, deduplicate explicitly. The handler,
not the framework, is the primary defense against duplicate events.**
