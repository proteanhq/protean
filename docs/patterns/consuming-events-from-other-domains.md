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

- **Language coupling**: Your code uses the Order domain's terminology.
  If the Order domain renames `items` to `line_items`, your handler breaks.

- **Your domain depends on the external schema**: Your domain depends on the
  exact structure of the external event. When the Order domain adds a field,
  removes one or changes its type, your domain has to change too.

- **Your releases are tied to the Order domain's releases**: When the Order
  domain deploys a new event version, your domain must update at the same time,
  or fail.

- **Order concepts enter your Fulfillment domain**: The Order domain's
  `OrderPlaced` event carries data shaped for the Order context. Your
  Fulfillment domain needs a subset of that data, differently structured. When
  your Fulfillment code processes the raw external event, you have to write
  that code in Order domain terms.

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

The subscriber is the **only** element in your domain that reads the external
event's structure. The handlers and projectors that run after the subscriber
receive only your domain's own commands and events.

!!!note "Co-located domains have a second option"
    The subscriber pattern applies to **distributed domains**, separate
    services communicating through a broker, or external systems you don't
    control.

    Sometimes multiple domains are in the **same repository and share the same
    event store**. For these domains Protean also supports
    `register_external_event()`, which gives your domain typed access to
    another domain's events without raw dict parsing. This is especially useful
    for process managers coordinating cross-domain workflows.

    See [Multi-Domain Applications, Cross-domain
    communication](../guides/multi-domain-applications.md#communicate-across-domains)
    for guidance on choosing between a subscriber and `register_external_event()`.

---

## How Protean Supports This

### Subscribers

Protean's `@domain.subscriber` listens to a broker stream and receives
raw `dict` payloads from external domains:

```python
--8<-- "patterns/consuming-events-from-other-domains/001.py:subscriber"
```

The subscriber:

1. Receives a raw `dict` payload from the broker, **not** a typed domain object
2. Inspects the payload to determine what kind of message it is
3. Extracts the data it needs
4. Constructs an internal `CreateShipment` command in the Fulfillment domain's language
5. Dispatches the command for processing by the domain's own handlers

!!!note "Payload shape"
    The examples on this page read flat JSON payloads, like the ones under
    [Handling External Schema Changes](#handling-external-schema-changes). That
    is the shape a producer outside Protean usually sends. A Protean domain
    that publishes through its outbox puts the event fields in
    `payload["data"]`. It puts the event type in
    `payload["metadata"]["headers"]["type"]`. [Publishing Events to External
    Brokers](publishing-events-to-external-brokers.md#step-4-consume-on-the-other-side)
    shows a subscriber that reads that shape.

!!!note
    Subscribers deliberately receive raw `dict` payloads rather than typed
    domain objects. This is the anti-corruption boundary. Your domain does
    **not** import or depend on the external domain's event classes. The raw
    `dict` payload keeps the external domain's event classes out of your
    internal model.

---

## Translate external events into your domain's language

### Translating to Commands

The most common pattern: translate external payloads into internal commands.
Your domain then processes the external input through its normal command
processing pipeline:

```python
--8<-- "patterns/consuming-events-from-other-domains/002.py:subscriber"
```

Notice the translation: the external domain uses `reference_id`, your domain
uses `order_id`. The external domain uses `transaction_id`, you use
`payment_id`. The subscriber maps between the two vocabularies.

### Translating to Domain Events

When the external event should trigger reactive processing across your domain
(not a specific command), translate it into an internal domain event:

```python
--8<-- "patterns/consuming-events-from-other-domains/003.py:subscriber"
```

The internal `ProductBecameUnavailable` event triggers your domain's own event
handlers and projectors, which use only your domain's language.

### Filtering Irrelevant Events

Not every external event is relevant to your domain. The subscriber filters:

```python
--8<-- "patterns/consuming-events-from-other-domains/004.py:subscriber"
```

### Enriching External Data

Sometimes your domain needs more context than the external event provides.
The subscriber can enrich the data from your own domain's state:

```python
--8<-- "patterns/consuming-events-from-other-domains/005.py:subscriber"
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
--8<-- "patterns/consuming-events-from-other-domains/006.py:both_versions"
```

Your domain's `CreateShipment` command, `Shipment` aggregate, and all handlers
remain unchanged. Only the subscriber code changes to match the new schema.

---

## Validate external events in the subscriber

External events may be malformed, carry unexpected data, or reference entities
that don't exist in your domain:

```python
--8<-- "patterns/consuming-events-from-other-domains/007.py:subscriber"
```

**Never trust external data.** Validate it at the subscriber boundary before
passing it into your domain.

!!! tip "Preserving the correlation chain"
    When your subscriber consumes events from external services, Protean
    automatically copies the `correlation_id` from the source event into your
    subscriber's processing context. Any commands dispatched inside the
    subscriber inherit the `correlation_id`, so you can trace one causal chain
    across service boundaries. See [Correlation and Causation
    IDs](../guides/observability/correlation-and-causation.md#keep-the-correlation-chain-across-service-boundaries)
    for details.

---

## Anti-Patterns

### Importing Event Classes from the External Domain

```python
# fragment
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
    With `register_external_event`, there is no import dependency. The shared
    contract is the type string, not the class.

### Processing External Events Without Translation

```python
# fragment
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
# fragment
# Anti-pattern: calling external API from subscriber
def __call__(self, payload: dict) -> None:
    # DON'T call back to the Order domain's API
    order_details = requests.get(
        f"http://order-service/orders/{payload['order_id']}"
    )
    ...
```

If the subscriber needs more data than the event carries, you have two options.
Ask the external domain to enrich its events (see [Design Events for
Consumers](design-events-for-consumers.md)), or maintain a local projection of
the external data.

---

## Summary

| Aspect | Direct Consumption | Subscriber Translation |
|--------|-------------------|----------------------|
| External schema coupling | High (throughout domain) | Low (subscriber only) |
| Language alignment | External terms leak in | Your domain's terms |
| Deployment independence | Low (must deploy together) | High (subscriber absorbs changes) |
| Error handling | Scattered | Centralized in subscriber |
| Testability | External dependency in tests | Mock external, test internal |

Subscribers are anti-corruption layers. They receive external events as raw
dicts, translate them into your domain's language, and dispatch internal
commands or events. The handlers and projectors that run after the subscriber
do not depend on where the message came from.

---

!!! tip "Related reading"
    **Concepts:**

    - [Subscribers](../concepts/building-blocks/subscribers.md): Anti-corruption layer at the domain boundary.

    **Guides:**

    - [Subscribers](../guides/consume-state/subscribers.md): Subscriber definition, broker configuration, and error handling.

    **Patterns:**

    - [Publishing Events to External Brokers](publishing-events-to-external-brokers.md): The producer side: delivering published events via the outbox.
