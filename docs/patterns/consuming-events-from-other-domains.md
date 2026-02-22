# Consuming Events from Other Domains

## The Problem

Your Fulfillment domain needs to react when the Order domain places an order.
The Order domain publishes an `OrderPlaced` event to a message broker. Your
domain subscribes to the broker channel and receives the event.

But the event was designed by the Order domain, using the Order domain's
language. It contains fields named according to the Order domain's ubiquitous
language, structured according to the Order domain's aggregate boundaries, and
versioned according to the Order domain's release schedule.

If your Fulfillment domain consumes this event directly:

- **Language coupling.** Your code uses the Order domain's terminology.
  If the Order domain renames `items` to `line_items`, your handler breaks.

- **Schema coupling.** Your domain depends on the exact structure of the
  external event. Field additions, removals, or type changes propagate into
  your domain.

- **Release coupling.** When the Order domain deploys a new event version,
  your domain must update simultaneously -- or fail.

- **Conceptual leaking.** The Order domain's `OrderPlaced` event carries data
  shaped for the Order context. Your Fulfillment domain needs a subset of that
  data, differently structured. Processing the raw external event forces
  Fulfillment to think in Order domain terms.

The root cause: **consuming external events without translation creates
coupling between bounded contexts that should be autonomous**.

---

## The Pattern

Use a **subscriber** at the domain boundary as an anti-corruption layer.
The subscriber receives the external event, translates it into your domain's
language, and dispatches an internal command or domain event.

```
External Domain                  Your Domain Boundary                Your Domain
┌───────────┐    Broker     ┌──────────────────┐    Command/Event    ┌─────────┐
│ Order      │ ──────────►  │ Subscriber        │ ──────────────►    │ Handler │
│ domain     │   OrderPlaced│ (anti-corruption) │  CreateShipment    │         │
│            │              │ translates to     │  (your language)   │         │
└───────────┘              │ your language     │                    └─────────┘
                            └──────────────────┘
```

The subscriber is the **only place** in your domain that knows about the
external event's structure. Everything downstream works with your domain's
own commands and events.

---

## How Protean Supports This

### Subscribers

Protean's `@domain.subscriber` listens to a broker channel and receives
messages from external domains:

```python
@domain.subscriber(channel="orders")
class OrderEventsSubscriber(BaseSubscriber):

    @handle(ExternalOrderPlaced)
    def on_order_placed(self, event: ExternalOrderPlaced):
        # Translate external event into internal command
        current_domain.process(
            CreateShipment(
                order_id=event.order_id,
                customer_id=event.customer_id,
                items=[
                    {"product_id": item["product_id"],
                     "quantity": item["quantity"]}
                    for item in event.items
                ],
                shipping_priority="standard",
            )
        )
```

The subscriber:
1. Receives the external `ExternalOrderPlaced` event from the broker
2. Extracts the data it needs
3. Constructs an internal `CreateShipment` command in the Fulfillment domain's language
4. Dispatches the command for processing by the domain's own handlers

### Define Your Own Event Classes

Even though the external domain published the event, your domain defines its
own class to deserialize it:

```python
# Your domain's representation of the external event
# NOT imported from the Order domain
@domain.event(part_of=Shipment)
class ExternalOrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float()
    placed_at: DateTime()
```

This class mirrors the external event's structure but belongs to **your**
domain. If the external domain adds fields you don't need, your class ignores
them. If they change field names, you update this one class -- not your entire
domain.

---

## The Translation Layer

### Translating to Commands

The most common pattern: translate external events into internal commands.
This funnels external stimuli through your domain's normal command processing
pipeline:

```python
@domain.subscriber(channel="payments")
class PaymentEventsSubscriber(BaseSubscriber):

    @handle(ExternalPaymentConfirmed)
    def on_payment_confirmed(self, event: ExternalPaymentConfirmed):
        current_domain.process(
            MarkOrderPaid(
                order_id=event.reference_id,  # External field name
                payment_id=event.transaction_id,  # Different naming
                amount=event.amount,
                currency=event.currency_code,  # Different naming
                paid_at=event.confirmed_at,  # Different naming
            )
        )
```

Notice the translation: the external domain uses `reference_id`, your domain
uses `order_id`. The external domain uses `transaction_id`, you use
`payment_id`. The subscriber maps between the two vocabularies.

### Translating to Domain Events

When the external event should trigger reactive processing across your domain
(not a specific command), translate it into an internal domain event:

```python
@domain.subscriber(channel="inventory-external")
class ExternalInventorySubscriber(BaseSubscriber):

    @handle(ExternalStockDepleted)
    def on_stock_depleted(self, event: ExternalStockDepleted):
        # Translate to internal event
        repo = current_domain.repository_for(Product)
        product = repo.get(event.sku)

        product.raise_(ProductBecameUnavailable(
            product_id=product.product_id,
            reason="external_stock_depleted",
        ))
        repo.add(product)
```

The internal `ProductBecameUnavailable` event triggers your domain's own
event handlers and projectors, all speaking your domain's language.

### Filtering Irrelevant Events

Not every external event is relevant to your domain. The subscriber filters:

```python
@domain.subscriber(channel="orders")
class OrderEventsSubscriber(BaseSubscriber):

    @handle(ExternalOrderPlaced)
    def on_order_placed(self, event: ExternalOrderPlaced):
        # Only create shipments for physical items
        physical_items = [
            item for item in event.items
            if item.get("type") != "digital"
        ]

        if not physical_items:
            return  # Nothing for Fulfillment to do

        current_domain.process(
            CreateShipment(
                order_id=event.order_id,
                customer_id=event.customer_id,
                items=physical_items,
            )
        )
```

### Enriching External Data

Sometimes your domain needs more context than the external event provides.
The subscriber can enrich the data from your own domain's state:

```python
@domain.subscriber(channel="orders")
class OrderEventsSubscriber(BaseSubscriber):

    @handle(ExternalOrderPlaced)
    def on_order_placed(self, event: ExternalOrderPlaced):
        # Enrich with data from our domain
        customer_repo = current_domain.repository_for(CustomerProfile)
        customer = customer_repo.get(event.customer_id)

        current_domain.process(
            CreateShipment(
                order_id=event.order_id,
                customer_id=event.customer_id,
                shipping_address=customer.default_shipping_address,
                shipping_priority=customer.shipping_tier,
                items=event.items,
            )
        )
```

---

## Handling External Schema Changes

When the external domain changes its event schema, only the subscriber needs
to update:

### Before: External event v1

```python
class ExternalOrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    items: List(required=True)
    total: Float()
```

### After: External event v2 (renamed field)

```python
class ExternalOrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    line_items: List(required=True)  # Renamed from 'items'
    subtotal: Float()                # Renamed from 'total'
    tax: Float()
    total: Float()                   # Now includes tax
```

Only the subscriber changes:

```python
@handle(ExternalOrderPlaced)
def on_order_placed(self, event: ExternalOrderPlaced):
    # Update the field mapping
    items = getattr(event, 'line_items', None) or getattr(event, 'items', [])

    current_domain.process(
        CreateShipment(
            order_id=event.order_id,
            items=items,
        )
    )
```

Your domain's `CreateShipment` command, `Shipment` aggregate, and all handlers
remain unchanged. The schema change is absorbed by the subscriber.

---

## Error Handling

External events may be malformed, carry unexpected data, or reference entities
that don't exist in your domain:

```python
@domain.subscriber(channel="orders")
class OrderEventsSubscriber(BaseSubscriber):

    @handle(ExternalOrderPlaced)
    def on_order_placed(self, event: ExternalOrderPlaced):
        # Validate the external data before trusting it
        if not event.order_id:
            logger.warning(
                f"Received OrderPlaced without order_id, skipping"
            )
            return

        if not event.items:
            logger.warning(
                f"Received OrderPlaced with no items for {event.order_id}"
            )
            return

        try:
            current_domain.process(
                CreateShipment(
                    order_id=event.order_id,
                    customer_id=event.customer_id,
                    items=event.items,
                )
            )
        except ValidationError as e:
            logger.error(
                f"Failed to process OrderPlaced {event.order_id}: {e}"
            )
            # Don't re-raise -- the external event was received,
            # the error is in our translation or domain rules.
            # Log for investigation rather than blocking the subscription.
```

**Key principle:** Never trust external data. Validate it at the subscriber
boundary before passing it into your domain.

---

## Anti-Patterns

### Importing Event Classes from the External Domain

```python
# Anti-pattern: importing from another domain
from order_domain.events import OrderPlaced

@domain.subscriber(channel="orders")
class OrderEventsSubscriber(BaseSubscriber):

    @handle(OrderPlaced)  # Direct dependency on external code
    def on_order_placed(self, event: OrderPlaced):
        ...
```

This creates a code-level dependency. Your domain can't deploy without the
Order domain's code. See [Sharing Event Classes Across
Domains](sharing-event-classes-across-domains.md) for alternatives.

### Processing External Events Without Translation

```python
# Anti-pattern: using external event directly in handler
@domain.event_handler(part_of=Shipment)
class ShipmentEventHandler(BaseEventHandler):

    @handle(ExternalOrderPlaced)  # External event in an internal handler
    def on_order_placed(self, event: ExternalOrderPlaced):
        shipment = Shipment(
            order_id=event.order_id,
            items=event.items,  # External field structure leaks in
        )
        ...
```

The internal event handler now depends on the external event's structure.
Use a subscriber to translate first.

### Calling Back to the External Domain

```python
# Anti-pattern: calling external API from subscriber
@handle(ExternalOrderPlaced)
def on_order_placed(self, event: ExternalOrderPlaced):
    # DON'T call back to the Order domain's API
    order_details = requests.get(
        f"http://order-service/orders/{event.order_id}"
    )
    ...
```

If the subscriber needs more data than the event carries, either request that
the external domain enrich its events (see [Design Events for
Consumers](design-events-for-consumers.md)) or maintain a local projection
of the external data.

---

## Summary

| Aspect | Direct Consumption | Subscriber Translation |
|--------|-------------------|----------------------|
| External schema coupling | High (throughout domain) | Low (subscriber only) |
| Language alignment | External terms leak in | Your domain's terms |
| Deployment independence | Low (must deploy together) | High (subscriber absorbs changes) |
| Error handling | Scattered | Centralized in subscriber |
| Testability | External dependency in tests | Mock external, test internal |

The principle: **subscribers are anti-corruption layers. They receive external
events, translate them into your domain's language, and dispatch internal
commands or events. Nothing downstream knows or cares that the stimulus came
from outside.**

---

!!! tip "Related reading"
    **Concepts:**

    - [Subscribers](../core-concepts/domain-elements/subscribers.md) — Anti-corruption layer at the domain boundary.

    **Guides:**

    - [Subscribers](../guides/consume-state/subscribers.md) — Subscriber definition, broker configuration, and error handling.
