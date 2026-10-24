# Multiple Events Flow

An aggregate that raises different events from different lifecycle methods, with multiple handlers reacting to different events. Examples: a shipment (dispatched, delivered), an order (placed, paid, shipped), an account (registered, activated, suspended).

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

The `Shipment` aggregate raises these events from its lifecycle methods:

```python
@domain.aggregate
class Shipment:
    shipment_id: Identifier(identifier=True)
    order_id: Identifier(required=True)
    carrier: String(required=True)
    status: String(default="created")
    tracking_info: String()
    delivered_at: DateTime()

    def dispatch(self):
        if self.status != "created":
            raise ValueError(f"Cannot dispatch shipment in '{self.status}' status")
        self.status = "dispatched"
        self.raise_(ShipmentDispatched(
            shipment_id=self.shipment_id,
            order_id=self.order_id,
            carrier=self.carrier,
        ))

    def deliver(self, delivered_at):
        if self.status != "dispatched":
            raise ValueError(f"Cannot deliver shipment in '{self.status}' status")
        self.status = "delivered"
        self.delivered_at = delivered_at
        self.raise_(ShipmentDelivered(
            shipment_id=self.shipment_id,
            order_id=self.order_id,
            delivered_at=delivered_at,
        ))
```

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

### Multiple Handlers for the Same Event

The notification handler belongs to a separate `Notification` aggregate:

```python
@domain.aggregate
class Notification:
    recipient: String(required=True)
    message: String(required=True)
    notification_type: String(required=True)
```

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

- Both `ShipmentEventHandler` and `ShipmentNotifier` process `ShipmentDispatched`
- Each handler runs independently in its own UnitOfWork
- `ShipmentNotifier` sits in Shipment's cluster because it reacts to Shipment's events. `SendNotification` is `part_of="Notification"`, and Notification's command handler does the write
- Events are delivered at least once, so `notification_id` is built from the shipment id and the event type. Notification's command handler adds the alert only when `repository.get` raises `ObjectNotFoundError`

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
- [Same-aggregate event flow](./same-aggregate-flow.md): Single event, same-aggregate handler
- [Cross-aggregate event flow](./cross-aggregate-flow.md): Event triggers side effect in another aggregate
- [event skill](../../event/SKILL.md): Event definition reference
- [event-handler skill](../../event-handler/SKILL.md): Handler reference
