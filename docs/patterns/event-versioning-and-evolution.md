# Event Versioning and Evolution

## The Problem

Six months after launch, the business asks for a change: orders should now
track a `discount_code` field. The developer adds the field to the `Order`
aggregate and to the `OrderPlaced` event:

```python
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    items = List(required=True)
    total = Float(required=True)
    discount_code = String()  # New field
```

The change works for new orders. But in an event-sourced system, the event
store contains thousands of old `OrderPlaced` events that were written
*without* `discount_code`. When the system replays these events to rebuild
an aggregate, the old events don't match the new class definition. If
`discount_code` were marked `required=True`, every historical event would
fail validation.

Even in non-event-sourced systems, event handlers and projectors process
events from a stream. When a consumer catches up on historical events after
a deployment, it encounters old events with the old schema. If the consumer
expects the new field, it breaks.

The fundamental tension: **events are immutable facts stored forever, but the
domain model evolves continuously**.

This tension produces specific failure modes:

- **Deserialization failures.** Old events lack new required fields. The
  deserializer raises an error, halting event replay or subscription processing.

- **Consumer breakage.** A projector expects `event.discount_code` but
  encounters an old event without it. The projector crashes or produces
  incorrect projections.

- **Silent data corruption.** An old event has a field with different semantics
  than the current definition. The consumer processes it with current-version
  logic, producing subtly wrong results.

- **Deployment coupling.** If all consumers must be updated simultaneously when
  an event schema changes, you lose the ability to deploy services independently.

---

## The Pattern

Evolve event schemas **backward-compatibly** by default. When backward
compatibility is impossible, use explicit versioning and transformation
strategies to bridge old and new schemas.

The golden rules:

1. **New fields get defaults.** Always.
2. **Old fields are never removed.** They can be deprecated but must remain
   deserializable.
3. **Semantics never change.** A field's meaning is permanent. If the meaning
   changes, create a new field or a new event type.
4. **Breaking changes create new event types.** If none of the above work, the
   old event type is retired and a new one takes its place.

---

## Backward-Compatible Changes

These changes are safe and require no versioning strategy:

### Adding Optional Fields with Defaults

The most common evolution. Add a new field with a default value that preserves
the behavior of events written before the field existed:

```python
# Version 1: original event
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    items = List(required=True)
    total = Float(required=True)


# Version 2: added discount_code and channel
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    items = List(required=True)
    total = Float(required=True)
    discount_code = String(default=None)    # New, optional
    channel = String(default="web")         # New, with sensible default
```

Old events deserialize successfully: `discount_code` is `None`, `channel` is
`"web"`. Consumers that don't know about the new fields ignore them. Consumers
that do know about them handle `None` / `"web"` as the legacy case.

**Rules for adding fields:**

- Never mark new fields as `required=True` on an existing event type
- Choose defaults that preserve pre-change behavior
- Document when the field was added (useful for consumers that reason about
  event history)

### Adding New Event Types

When a new business operation is introduced, create a new event type:

```python
# New business operation: gift wrapping
@domain.event(part_of=Order)
class OrderGiftWrapped(BaseEvent):
    order_id = Identifier(required=True)
    wrapping_style = String(required=True)
    gift_message = String()
```

New event types don't affect existing consumers. Consumers that don't handle
`OrderGiftWrapped` simply ignore it.

### Widening Field Types

Changing a field's type to accept a broader range of values is safe if the
serialization format is compatible:

```python
# Before: status as String with limited choices
status = String(choices=["pending", "shipped"])

# After: status with more choices
status = String(choices=["pending", "shipped", "returned", "refunded"])
```

Old events still match. New events use the expanded set. Consumers should
already handle unknown values gracefully.

---

## Strategies for Breaking Changes

When backward-compatible evolution isn't possible, use one of these strategies:

### Strategy 1: New Event Type

The cleanest approach for significant schema changes. Create a new event type
and keep the old one for historical events:

```python
# Original event (keep for historical data)
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    items = List(required=True)
    total = Float(required=True)


# New event for the updated business process
@domain.event(part_of=Order)
class OrderPlacedV2(BaseEvent):
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    line_items = List(required=True)       # Renamed from 'items'
    subtotal = Float(required=True)        # Changed semantics
    tax = Float(required=True)             # New required field
    total = Float(required=True)
    currency = String(required=True)       # New required field
```

The aggregate now raises `OrderPlacedV2`. Consumers must handle both types:

```python
@domain.event_handler(part_of=Fulfillment)
class FulfillmentEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def on_order_placed_v1(self, event: OrderPlaced):
        """Handle historical events."""
        self._create_fulfillment(
            order_id=event.order_id,
            items=event.items,
            total=event.total,
            currency="USD",  # Assumed for v1 events
        )

    @handle(OrderPlacedV2)
    def on_order_placed_v2(self, event: OrderPlacedV2):
        """Handle current events."""
        self._create_fulfillment(
            order_id=event.order_id,
            items=event.line_items,
            total=event.total,
            currency=event.currency,
        )

    def _create_fulfillment(self, order_id, items, total, currency):
        # Shared implementation
        repo = current_domain.repository_for(Fulfillment)
        fulfillment = Fulfillment(
            order_id=order_id,
            items=items,
            total=total,
            currency=currency,
        )
        repo.add(fulfillment)
```

**When to use:** Significant structural changes, renamed fields, changed
semantics, new required fields without meaningful defaults.

### Strategy 2: Upcasting on Read

Transform old events to the new schema when they're read from the event store,
before they reach the handler. This keeps handlers simple -- they only see the
latest schema.

```python
# Define an upcaster that transforms old events to new schema
def upcast_order_placed(old_event_data: dict) -> dict:
    """Transform OrderPlaced v1 data to v2 schema."""
    return {
        "order_id": old_event_data["order_id"],
        "customer_id": old_event_data["customer_id"],
        "line_items": old_event_data.get("items", []),  # Renamed field
        "subtotal": old_event_data["total"],             # Same value
        "tax": 0.0,                                       # Default for old events
        "total": old_event_data["total"],
        "currency": "USD",                                # Default for old events
    }
```

Upcasting happens between deserialization and handler dispatch. The handler
always receives the latest schema, regardless of which version was stored.

**When to use:** Field renames, type changes, or calculated new fields where
a reasonable transformation exists. Useful when you don't want handlers to
know about historical schemas.

**Trade-off:** Upcasting adds a processing layer and must be maintained as
schemas evolve further. Each version needs an upcaster to the next.

### Strategy 3: Tolerant Reader

Design consumers to be tolerant of missing, extra, or unexpected fields:

```python
@domain.event_handler(part_of=Analytics)
class AnalyticsEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def track_order(self, event: OrderPlaced):
        # Use getattr with defaults for fields that may not exist
        channel = getattr(event, "channel", "unknown")
        discount = getattr(event, "discount_code", None)
        currency = getattr(event, "currency", "USD")

        self._record_analytics(
            order_id=event.order_id,
            total=event.total,
            channel=channel,
            has_discount=discount is not None,
            currency=currency,
        )
```

The consumer handles whatever fields are present and provides sensible defaults
for missing ones. This is pragmatic but can lead to scattered default-handling
logic.

**When to use:** Consumers that don't require strict schemas (analytics,
logging, monitoring). Not suitable for consumers that need precise data
(financial calculations, projections).

---

## Fact Events and Schema Evolution

Protean's `fact_events=True` auto-generates events from the aggregate's
current schema. When the aggregate changes, fact events automatically reflect
the new schema.

This simplifies some evolution scenarios but creates others:

```python
@domain.aggregate(fact_events=True)
class Order:
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    items = HasMany(OrderItem)
    status = String(default="draft")
    total = Float(default=0.0)
    currency = String(default="USD")  # New field
```

**Benefits:**

- Fact events always match the aggregate's current schema
- No manual event class maintenance
- Projections that mirror the aggregate get updates automatically

**Risks:**

- Historical fact events in the store have the old schema (no `currency`)
- Consumers that process historical fact events must handle missing fields
- Adding a new required field to the aggregate changes the fact event schema

**Mitigation:**

- Treat fact events as eventually-consistent snapshots, not as precise
  historical records
- Use delta events for precise historical semantics
- Always add fields to aggregates with defaults when using fact events

---

## Naming Conventions for Versioned Events

When creating new event versions, use clear naming:

| Approach | Example | When to Use |
|----------|---------|-------------|
| Suffix version | `OrderPlacedV2` | Clear versioning, easy to search |
| Descriptive name | `OrderPlacedWithCurrency` | When the change has business meaning |
| Namespace | `v2.OrderPlaced` | When many events change together |

The suffix approach (`V2`, `V3`) is the most common because it's simple and
unambiguous. Avoid descriptive names for minor changes -- they become unwieldy
(`OrderPlacedWithCurrencyAndDiscount`).

---

## Event Store Considerations

### Never Modify Stored Events

Events in the store are immutable historical records. Never update, delete, or
"fix" stored events. If an event was written incorrectly, handle it through
upcasting or compensating events.

```python
# NEVER do this:
# event_store.update(event_id, corrected_data)

# Instead, raise a correcting event:
@domain.event(part_of=Order)
class OrderTotalCorrected(BaseEvent):
    order_id = Identifier(required=True)
    old_total = Float(required=True)
    new_total = Float(required=True)
    correction_reason = String(required=True)
```

### Stream Position After Schema Changes

When you deploy a schema change, existing events in the stream remain
unchanged. New events use the new schema. The stream contains a mix of old
and new schemas. Consumers must handle both.

### Replaying from the Beginning

If you replay an event-sourced aggregate from the beginning of its stream,
it will encounter every historical event version. The aggregate's `@apply`
handlers must handle all versions:

```python
@domain.aggregate(is_event_sourced=True)
class Order(BaseAggregate):
    # ... fields ...

    @apply
    def on_order_placed(self, event: OrderPlaced):
        """Handle v1 OrderPlaced events."""
        self.customer_id = event.customer_id
        self.items = event.items
        self.total = event.total
        self.currency = getattr(event, "currency", "USD")

    @apply
    def on_order_placed_v2(self, event: OrderPlacedV2):
        """Handle v2 OrderPlaced events."""
        self.customer_id = event.customer_id
        self.items = event.line_items
        self.total = event.total
        self.currency = event.currency
```

---

## Migration Strategies

### The Copy-Transform Pattern

For large schema changes, create a new stream with transformed events:

1. Read events from the old stream
2. Transform each event to the new schema
3. Write to a new stream
4. Switch consumers to the new stream
5. Keep the old stream for audit purposes

This is a heavy operation but provides a clean break from historical schemas.

### The Dual-Write Transition

During a migration period, produce both old and new event types:

```python
def place(self):
    self.status = "placed"

    # Raise both old and new events during transition
    self.raise_(OrderPlaced(
        order_id=self.order_id,
        customer_id=self.customer_id,
        items=[item.to_dict() for item in self.items],
        total=self.total,
    ))

    self.raise_(OrderPlacedV2(
        order_id=self.order_id,
        customer_id=self.customer_id,
        line_items=[item.to_dict() for item in self.items],
        subtotal=self.total - self.tax,
        tax=self.tax,
        total=self.total,
        currency=self.currency,
    ))
```

Consumers migrate from `OrderPlaced` to `OrderPlacedV2` at their own pace.
Once all consumers have migrated, stop raising the old event.

**Trade-off:** The aggregate raises two events for every operation during
the transition period. Events in the store contain duplicated information.
Keep the transition period short.

---

## Anti-Patterns

### Changing Field Semantics

```python
# Version 1: total includes tax
class OrderPlaced(BaseEvent):
    total = Float()  # Includes tax

# Version 2: total excludes tax (BREAKING CHANGE)
class OrderPlaced(BaseEvent):
    total = Float()  # Now excludes tax
```

The field name is the same, but the meaning changed. Every consumer that
processes historical events will compute wrong values. Create a new field
instead: `subtotal` for the tax-exclusive amount.

### Removing Fields

```python
# Version 1
class OrderPlaced(BaseEvent):
    customer_name = String()

# Version 2: removed customer_name (BREAKING CHANGE)
class OrderPlaced(BaseEvent):
    pass  # customer_name removed
```

Consumers that expect `customer_name` will crash. Even if no current consumer
needs it, historical events in the store still carry the field. Keep the field
and deprecate it in documentation.

### Required Fields on Existing Events

```python
# NEVER add a required field to an existing event
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    currency = String(required=True)  # BREAKS all historical events
```

Historical events don't have `currency`. Deserialization fails. Always use
defaults on new fields for existing event types.

---

## Decision Guide

| Change Type | Safe? | Strategy |
|-------------|-------|----------|
| Add optional field with default | Yes | Just add it |
| Add new event type | Yes | Add handler methods |
| Add more choices to a field | Yes | Consumers handle unknowns |
| Rename a field | No | New event type or upcasting |
| Remove a field | No | Deprecate, don't remove |
| Change field type | No | New field or new event type |
| Change field semantics | No | New field name |
| Add required field without default | No | Use default, or new event type |
| Split event into multiple events | No | New event types + transition period |

---

## Summary

| Aspect | Approach |
|--------|----------|
| Adding data | Optional fields with defaults |
| New operations | New event types |
| Renamed fields | New event type (V2) or upcasting |
| Changed semantics | New field name or new event type |
| Consumer compatibility | Tolerant reader pattern |
| Historical replay | Handle all versions in @apply handlers |
| Large migrations | Copy-transform or dual-write transition |
| Stored events | Never modified, only appended to |

The principle: **events are permanent contracts. Evolve them the way you
evolve APIs -- additive changes are safe, breaking changes require versioning.
New fields get defaults. Old fields are never removed. Semantics never change.
When in doubt, create a new event type.**
