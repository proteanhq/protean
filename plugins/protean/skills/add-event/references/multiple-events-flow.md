# Multiple Events Flow

An aggregate that raises different events from different lifecycle methods, with multiple handlers reacting to different events. This is the common real-world pattern where an aggregate's lifecycle generates several distinct events.

## Overview

Most aggregates raise multiple events throughout their lifecycle:
1. Each state transition raises a different event
2. Same-aggregate handlers process some events (internal side effects)
3. Other handlers in the same cluster hand off to other aggregates with commands (external side effects)
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
- A second handler, `ShipmentNotifier`, also `part_of=Shipment`, that issues a `SendNotification` command for each shipment event
- `Notification`'s command handler creates the alert, and skips one that already exists
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

# Handler 2: Cross-aggregate (notifications), still in Shipment's cluster
@domain.event_handler(part_of=Shipment)
class ShipmentNotifier:
    @handle(ShipmentDispatched)
    def on_dispatched(self, event):
        current_domain.process(
            SendNotification(
                notification_id=f"{event.shipment_id}:dispatch",
                recipient=event.order_id,
                message=f"Shipment {event.shipment_id} dispatched",
                notification_type="dispatch",
            )
        )
```

- Unlike commands (which have exactly one handler), events support multiple handlers
- Both `ShipmentEventHandler` and `ShipmentNotifier` process `ShipmentDispatched`
- Each handler runs independently in its own UnitOfWork
- `ShipmentNotifier` sits in Shipment's cluster because it reacts to Shipment's events. `SendNotification` is `part_of="Notification"`, and Notification's command handler does the write
- Events are delivered at least once, so `notification_id` is built from the shipment id and the event type. Notification's command handler adds the alert only when `repository.get` raises `ObjectNotFoundError`

## Adding a New Event to an Existing Flow

When adding a new event to an aggregate that already has events and handlers:

1. **Define the new event** with `part_of` pointing to the aggregate
2. **Add the aggregate method** that raises the event
3. **Add a `@handle` method** to the existing handler class (don't create a new handler class for the same aggregate)
4. **Optionally hand off to another aggregate** for the new event: a handler in this cluster issues a command, and the other aggregate's command handler does the write (see [cross-aggregate flow](./cross-aggregate-flow.md))

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
├── handle_shipment_events.py    # ShipmentNotifier (issues SendNotification)
└── ...

src/myapp/notification/
├── notification.py              # Notification aggregate
└── send_notification.py         # SendNotification command + its command handler
```

## Testing

When testing multiple events:
1. Test each aggregate method independently (verify event is raised)
2. Test each handler method independently
3. Test the full lifecycle (create → dispatch → deliver) end-to-end
4. Verify both handlers fire: tracking info changes and one notification exists per event

## Related
- [Same-aggregate event flow](./same-aggregate-flow.md) - Single event, same-aggregate handler
- [Cross-aggregate event flow](./cross-aggregate-flow.md) - Event triggers side effect in another aggregate
- [event skill](../../event/SKILL.md) - Event definition reference
- [event-handler skill](../../event-handler/SKILL.md) - Handler reference
