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
`PUBLISHED_NO_EXTERNAL_BROKER`, so name the broker the other context reads.

Turn the outbox on as well. `Domain.has_outbox` is false under the default
`event_store` subscription, and naming an external broker does not change that.
With the outbox off the unit of work writes no outbox row, so nothing is
dispatched and the other context never hears anything:

```python
sales.config["server"]["default_subscription_type"] = "stream"
sales.config["brokers"]["events"] = {"provider": "inline"}
sales.config["outbox"]["external_brokers"] = ["events"]
```

### 1b. The consuming context declares the same broker

Broker names are local to a `Domain`. A second `Domain` does not see the first
one's `events` entry, so the consumer declares its own pointing at the same
broker infrastructure, and the subscriber binds to it by name. Leave this out and
sales dispatches to its `events` broker while fulfilment listens on its own
`default`, so the deployed pair stays silent while a one-process demo still
appears to work:

```python
fulfilment.config["brokers"]["events"] = {"provider": "inline"}
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

Two things about that shape. `OutboxProcessor` publishes each row on
`metadata.domain.stream_category`, so the stream to subscribe to is the
publishing aggregate's category, `sales::order`. And it publishes what
`Message.to_external_dict()` returns, so the message arrives as
`{"data": ..., "metadata": ...}` and the event's fields sit under `"data"`.
The category stream carries every event of that aggregate, so the subscriber also
checks the type header and returns early on the ones it does not act on:

The type it checks is written as a string. Importing `OrderPlaced` from sales
would restore the dependency the extraction removed, and once the two contexts
run as separate processes that import does not exist. The name and the fields
unpacked below are the whole contract fulfilment depends on:

```python
SALES_ORDER_PLACED = "Sales.OrderPlaced.v1"


@fulfilment.subscriber(stream="sales::order", broker="events")
class OrderPlacedSubscriber:
    def __call__(self, payload: dict) -> None:
        if payload["metadata"]["headers"]["type"] != SALES_ORDER_PLACED:
            return
        data = payload["data"]
        command = CreateShipment(
            order_id=data["order_id"],
            address=data["address"],
        )
        fulfilment.process(command)
```

Broker delivery is at-least-once, so a redelivered `OrderPlaced` runs this
subscriber again. This example keeps the seam in focus and does nothing about
that, which is fine for a demo and wrong for production: `CreateShipment` would
open a second shipment for the same order. Give the consumer a way to recognise
work it has already done, such as a uniqueness constraint on the identifier it
holds across the seam (`order_id` here).

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
