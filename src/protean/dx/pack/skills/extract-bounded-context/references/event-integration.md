# Event integration across the seam

After the split, the two contexts still need to work together. They do it by
sending events across the seam. The context that owns a change publishes an event
as a fact about what happened. The other context reads that event and acts on it.
A message broker carries the event from one to the other.

## The moves

### 1. The owning context publishes an event

The context that owns the change raises a domain event and marks it published, so
it is part of that context's published language:

```python
@sales.event(part_of="Order", published=True)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    address = String(required=True)
```

`published=True` says the event leaves this context. `check` then expects no
in-domain handler for it, and the domain dispatches it to the brokers named in
`outbox.external_brokers`. Without an external broker configured, `check` reports
`PUBLISHED_NO_EXTERNAL_BROKER`, so name the broker the other context reads:

```python
sales.config["brokers"]["events"] = {"provider": "inline"}
sales.config["outbox"]["external_brokers"] = ["events"]
```

### 2. The event carries plain data

A published event carries the fields the other context needs as plain values.
Keep a `Reference` into the publishing context out of it. That is the whole
point of the extraction: the consumer holds what it was told, and the two
contexts stay independent.

### 3. The consuming context translates at a subscriber

The other context consumes the raw message with a subscriber and translates it
into its own command. The subscriber is the anti-corruption layer: it is the one
place that understands the external event's shape, so the rest of the context
speaks only its own language.

```python
@fulfilment.subscriber(stream="sales_order_placed")
class OrderPlacedSubscriber:
    def __call__(self, payload: dict) -> None:
        command = CreateShipment(
            order_id=payload["order_id"],
            address=payload["address"],
        )
        fulfilment.process(command)
```

See [add-subscriber-flow](../../add-subscriber-flow/SKILL.md) for the subscriber
and anti-corruption-layer pattern in full.

## Holding the other context by identity

The consuming aggregate holds the far side by its identifier, a plain
`Identifier` field:

```python
@fulfilment.aggregate
class Shipment:
    order_id = Identifier(required=True)
    address = String(required=True, max_length=200)
    status = String(default="pending", max_length=20)
```

`order_id` records which order this shipment is for. When fulfilment needs sales
data it does not hold, it asks sales through its published events. A `Reference`
here would pull the sales aggregate back across the seam and bring the cycle
back with it.
