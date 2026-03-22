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

!!!note "Co-located domains have a second option"
    This pattern applies to **distributed domains** — separate services
    communicating through a broker, or external systems you don't control.

    When multiple domains live in the **same repository and share the same
    event store**, Protean also supports `register_external_event()`, which
    gives your domain typed access to another domain's events without raw
    dict parsing. This is especially useful for process managers coordinating
    cross-domain workflows.

    See [Multi-Domain Applications — Cross-domain
    communication](../guides/multi-domain-applications.md#cross-domain-communication)
    for guidance on choosing between the two approaches.

---

## How Protean Supports This

### Subscribers

Protean's `@domain.subscriber` listens to a broker stream and receives
raw `dict` payloads from external domains:

```python
@domain.subscriber(stream="orders")
class OrderEventsSubscriber:

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type")

        if event_type == "OrderPlaced":
            # Translate external payload into internal command
            current_domain.process(
                CreateShipment(
                    order_id=payload["order_id"],
                    customer_id=payload["customer_id"],
                    items=[
                        {"product_id": item["product_id"],
                         "quantity": item["quantity"]}
                        for item in payload["items"]
                    ],
                    shipping_priority="standard",
                )
            )
```

The subscriber:
1. Receives a raw `dict` payload from the broker — **not** a typed domain object
2. Inspects the payload to determine what kind of message it is
3. Extracts the data it needs
4. Constructs an internal `CreateShipment` command in the Fulfillment domain's language
5. Dispatches the command for processing by the domain's own handlers

!!!note
    Subscribers deliberately receive raw `dict` payloads rather than typed
    domain objects. This is the anti-corruption boundary — your domain does
    **not** import or depend on the external domain's event classes. The raw
    dict is the firewall between external and internal models.

---

## The Translation Layer

### Translating to Commands

The most common pattern: translate external payloads into internal commands.
This funnels external stimuli through your domain's normal command processing
pipeline:

```python
@domain.subscriber(stream="payments")
class PaymentEventsSubscriber:

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type")

        if event_type == "PaymentConfirmed":
            current_domain.process(
                MarkOrderPaid(
                    order_id=payload["reference_id"],     # External field name
                    payment_id=payload["transaction_id"],  # Different naming
                    amount=payload["amount"],
                    currency=payload["currency_code"],     # Different naming
                    paid_at=payload["confirmed_at"],       # Different naming
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
@domain.subscriber(stream="inventory-external")
class ExternalInventorySubscriber:

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type")

        if event_type == "StockDepleted":
            repo = current_domain.repository_for(Product)
            product = repo.get(payload["sku"])

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
@domain.subscriber(stream="orders")
class OrderEventsSubscriber:

    def __call__(self, payload: dict) -> None:
        if payload.get("type") != "OrderPlaced":
            return  # Ignore event types we don't care about

        # Only create shipments for physical items
        physical_items = [
            item for item in payload["items"]
            if item.get("type") != "digital"
        ]

        if not physical_items:
            return  # Nothing for Fulfillment to do

        current_domain.process(
            CreateShipment(
                order_id=payload["order_id"],
                customer_id=payload["customer_id"],
                items=physical_items,
            )
        )
```

### Enriching External Data

Sometimes your domain needs more context than the external event provides.
The subscriber can enrich the data from your own domain's state:

```python
@domain.subscriber(stream="orders")
class OrderEventsSubscriber:

    def __call__(self, payload: dict) -> None:
        if payload.get("type") != "OrderPlaced":
            return

        # Enrich with data from our domain
        customer_repo = current_domain.repository_for(CustomerProfile)
        customer = customer_repo.get(payload["customer_id"])

        current_domain.process(
            CreateShipment(
                order_id=payload["order_id"],
                customer_id=payload["customer_id"],
                shipping_address=customer.default_shipping_address,
                shipping_priority=customer.shipping_tier,
                items=payload["items"],
            )
        )
```

---

## Handling External Schema Changes

When the external domain changes its event schema, only the subscriber needs
to update:

### Before: External payload v1

```json
{
    "type": "OrderPlaced",
    "order_id": "ord-123",
    "items": [...],
    "total": 99.99
}
```

### After: External payload v2 (renamed field)

```json
{
    "type": "OrderPlaced",
    "order_id": "ord-123",
    "line_items": [...],
    "subtotal": 79.99,
    "tax": 20.00,
    "total": 99.99
}
```

Only the subscriber changes:

```python
def __call__(self, payload: dict) -> None:
    # Handle both v1 and v2 field names
    items = payload.get("line_items") or payload.get("items", [])

    current_domain.process(
        CreateShipment(
            order_id=payload["order_id"],
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
@domain.subscriber(stream="orders")
class OrderEventsSubscriber:

    def __call__(self, payload: dict) -> None:
        # Validate the external data before trusting it
        if not payload.get("order_id"):
            logger.warning("Received OrderPlaced without order_id, skipping")
            return

        if not payload.get("items"):
            logger.warning(
                f"Received OrderPlaced with no items for {payload['order_id']}"
            )
            return

        try:
            current_domain.process(
                CreateShipment(
                    order_id=payload["order_id"],
                    customer_id=payload["customer_id"],
                    items=payload["items"],
                )
            )
        except ValidationError as e:
            logger.error(
                f"Failed to process OrderPlaced {payload['order_id']}: {e}"
            )
            # Don't re-raise -- the external event was received,
            # the error is in our translation or domain rules.
            # Log for investigation rather than blocking the subscription.
```

**Key principle:** Never trust external data. Validate it at the subscriber
boundary before passing it into your domain.

!!! tip "Preserving the correlation chain"
    When consuming events from external services, the `correlation_id` from the
    source event is automatically bridged into your subscriber's processing
    context. Any commands dispatched inside the subscriber inherit it, stitching
    the causal chain across service boundaries. See
    [Correlation and Causation IDs](../guides/observability/correlation-and-causation.md#service-boundary-handling)
    for details.

---

## Anti-Patterns

### Importing Event Classes from the External Domain

```python
# Anti-pattern: importing from another domain's package
from order_domain.events import OrderPlaced

@domain.subscriber(stream="orders")
class OrderEventsSubscriber:
    def __call__(self, payload: dict) -> None:
        event = OrderPlaced(**payload)  # Direct dependency on external code
        ...
```

This creates a code-level dependency. Your domain can't deploy without the
Order domain's code. See [Sharing Event Classes Across
Domains](sharing-event-classes-across-domains.md) for alternatives.

!!!note
    This anti-pattern is about **importing classes from another domain's
    package**, creating a code dependency. It is distinct from
    `register_external_event()`, where you define your own event class in
    your domain and register it with the external event's type string.
    With `register_external_event`, there is no import dependency —
    the shared contract is the type string, not the class.

### Processing External Events Without Translation

```python
# Anti-pattern: using external payload directly in handler
@domain.event_handler(part_of=Shipment)
class ShipmentEventHandler(BaseEventHandler):

    @handle(SomeInternalEvent)
    def on_event(self, event):
        shipment = Shipment(
            order_id=external_payload["order_id"],  # External field structure leaks in
            items=external_payload["items"],
        )
        ...
```

The internal event handler now depends on the external event's structure.
Use a subscriber to translate first.

### Calling Back to the External Domain

```python
# Anti-pattern: calling external API from subscriber
def __call__(self, payload: dict) -> None:
    # DON'T call back to the Order domain's API
    order_details = requests.get(
        f"http://order-service/orders/{payload['order_id']}"
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
events as raw dicts, translate them into your domain's language, and dispatch
internal commands or events. Nothing downstream knows or cares that the
stimulus came from outside.**

---

!!! tip "Related reading"
    **Concepts:**

    - [Subscribers](../concepts/building-blocks/subscribers.md) — Anti-corruption layer at the domain boundary.

    **Guides:**

    - [Subscribers](../guides/consume-state/subscribers.md) — Subscriber definition, broker configuration, and error handling.

    **Patterns:**

    - [Publishing Events to External Brokers](publishing-events-to-external-brokers.md) — The producer side: delivering published events via the outbox.
