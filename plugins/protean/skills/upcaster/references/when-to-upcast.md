# When to Upcast

## Decision Table

| Change | Strategy | Why |
|--------|----------|-----|
| Add optional field with default | **No upcaster**: just add `default=` | Old events deserialize fine; missing field gets the default |
| Add required field with known default | **Upcast** | Old events need the new field to pass validation |
| Rename a field | **Upcast** | Old events have the old name; transformation is structural |
| Change field type (e.g., string→int) | **Upcast** | Old events have the old type; transformation is structural |
| Change data structure (flat→nested) | **Upcast** | Old events have flat fields; transformation is structural |
| Remove an unused field | **Upcast** (strip from old data) | Prevents unknown field errors during construction |
| Compute a derived field from existing data | **Upcast** | Old events don't have the field but have the source data |
| Change the meaning of a field | **New event type** | Can't transform meaning; consumers would compute wrong results |
| Fundamentally different business operation | **New event type** | Different intent, different schema, different handlers |
| Event applies to a different aggregate | **New event type** | Different aggregate, different stream |

## Backward-Compatible Changes (No Upcaster Needed)

These changes are always safe and require no upcaster. The examples use an `Order` aggregate:

```python
@domain.aggregate
class Order:
    currency = String()
```

### Adding optional fields with defaults

```python
# Before
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    amount = Float(required=True)

# After: just add with default
@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    amount = Float(required=True)
    discount_code = String(default=None)    # Safe: old events get None
    channel = String(default="web")         # Safe: old events get "web"
```

### Adding new event types

New event types don't affect existing events or consumers.

### Widening field choices

```python
# Before
status = String(choices=["pending", "shipped"])

# After: adding more choices is safe
status = String(choices=["pending", "shipped", "returned", "refunded"])
```

## When to Create a New Event Type Instead

Besides the three "New event type" rows in the table, create a new event type when there's no reasonable default: you can't compute the new field from old data (for example, old events didn't track the information at all).

## Limitations of Upcasting

- **No event type renaming**: If you rename `OrderCreated` to `OrderPlaced`, the type strings differ and upcasting can't bridge them. Use the "new event type" strategy.
- **No multi-event transformations**: An upcaster transforms one event at a time. You can't split one event into two or merge two events into one.
- **No eager/batch migration**: Upcasting is lazy (on-read only). If you need to physically rewrite the event store, use the copy-transform migration pattern.
- **No cross-event dependencies**: An upcaster can't look at other events in the stream. It only sees the single event's payload dict.

## Upcasting vs. Tolerant Reader

The **tolerant reader** pattern handles missing fields in consumer code:

```python
# Tolerant reader: scattered defensive code
@apply
def on_placed(self, event: OrderPlaced):
    self.currency = getattr(event, "currency", "USD")
```

**Upcasting** centralizes the transformation:

```python
# With the SKILL.md's UpcastV1ToV2 filling in `currency`, the handler stays clean
@apply
def on_placed(self, event: OrderPlaced):
    self.currency = event.currency  # Always present
```

**Prefer upcasting** for:
- Event-sourced aggregates (many handlers, clean @apply)
- Precise consumers (financial calculations, projections)
- Multiple consumers handling the same event

**Tolerant reader is acceptable** for:
- Analytics and monitoring (imprecise is okay)
- One-off consumers that will be retired
- When the change is truly optional
