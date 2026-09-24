# Multiple Events Flow

An aggregate that raises different events from different lifecycle methods, with multiple handlers reacting to different events. This is the common real-world pattern where an aggregate's lifecycle generates several distinct events.

## Overview

Most aggregates raise multiple events throughout their lifecycle:
1. Each state transition raises a different event
2. Same-aggregate handlers process some events (internal side effects)
3. Cross-aggregate handlers process other events (external side effects)
4. The same event can be handled by multiple independent handlers

Common use cases:
- Shipment lifecycle (dispatched → delivered) with tracking updates and notifications
- Order lifecycle (placed → paid → shipped → completed) with various side effects
- Account lifecycle (registered → activated → suspended) with emails and audit trails

## Code

The complete implementation is in [assets/add_event_multiple_events.py](../assets/add_event_multiple_events.py).

Key highlights:
- Shipment aggregate with `dispatch()` and `deliver()` methods, each raising a distinct event
- Same-aggregate `ShipmentEventHandler` with multiple `@handle` methods for tracking
- Cross-aggregate `NotificationHandler` that sends alerts for shipment events
- Both handlers independently process the same events

## Walkthrough

### Multiple Events on One Aggregate

```python
@domain.event(part_of="Shipment")
class ShipmentDispatched:
    shipment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    carrier: String(required=True)

@domain.event(part_of="Shipment")
class ShipmentDelivered:
    shipment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    delivered_at: DateTime(required=True)
```

- Each event carries data specific to that transition
- All events share `part_of="Shipment"`

### Same-Aggregate Handler with Multiple @handle Methods

```python
@domain.event_handler(part_of=Shipment)
class ShipmentEventHandler:
    @handle(ShipmentDispatched)
    def on_dispatched(self, event):
        # Generate tracking info
        ...

    @handle(ShipmentDelivered)
    def on_delivered(self, event):
        # Update tracking to delivered
        ...
```

- One handler class, multiple `@handle` methods
- Each method processes a different event type
- All belong to the same aggregate stream

### Multiple Handlers for the Same Event

```python
# Handler 1: Same-aggregate (tracking)
@domain.event_handler(part_of=Shipment)
class ShipmentEventHandler:
    @handle(ShipmentDispatched)
    def on_dispatched(self, event): ...

# Handler 2: Cross-aggregate (notifications)
@domain.event_handler(part_of=Notification, stream_category=Shipment.meta_.stream_category)
class NotificationHandler:
    @handle(ShipmentDispatched)
    def on_dispatched(self, event): ...
```

- Unlike commands (which have exactly one handler), events support multiple handlers
- Both `ShipmentEventHandler` and `NotificationHandler` process `ShipmentDispatched`
- Each handler runs independently in its own UnitOfWork

## Adding a New Event to an Existing Flow

When adding a new event to an aggregate that already has events and handlers:

1. **Define the new event** with `part_of` pointing to the aggregate
2. **Add the aggregate method** that raises the event
3. **Add a `@handle` method** to the existing handler class (don't create a new handler class for the same aggregate)
4. **Optionally add cross-aggregate handlers** for the new event

```python
# New event
@domain.event(part_of="Shipment")
class ShipmentReturned:
    shipment_id: Identifier(required=True)
    return_reason: String(required=True)

# Add method to existing aggregate
class Shipment:
    def initiate_return(self, reason):
        self.status = "returned"
        self.raise_(ShipmentReturned(
            shipment_id=self.shipment_id,
            return_reason=reason,
        ))

# Add @handle to existing handler
class ShipmentEventHandler:
    # ... existing handlers ...

    @handle(ShipmentReturned)
    def on_returned(self, event):
        # Handle the return
        ...
```

## File organization

```
src/myapp/shipment/
├── shipment.py                  # Aggregate with dispatch(), deliver()
├── shipment_dispatched.py       # ShipmentDispatched event + ShipmentEventHandler
├── shipment_delivered.py        # ShipmentDelivered event (handler in dispatched file)
└── ...

src/myapp/notification/
├── notification.py              # Notification aggregate
└── handle_shipment_events.py   # Cross-aggregate handler for Shipment events
```

## Testing

When testing multiple events:
1. Test each aggregate method independently (verify event is raised)
2. Test each handler method independently
3. Test the full lifecycle (create → dispatch → deliver) end-to-end
4. Verify both same-aggregate and cross-aggregate handlers fire

## Related
- [Same-aggregate event flow](./same-aggregate-flow.md) - Single event, same-aggregate handler
- [Cross-aggregate event flow](./cross-aggregate-flow.md) - Event triggers side effect in another aggregate
- [event skill](../../event/SKILL.md) - Event definition reference
- [event-handler skill](../../event-handler/SKILL.md) - Handler reference
