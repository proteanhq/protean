---
name: extract-bounded-context
description: Extract a set of aggregates out of one Protean Domain into a second Domain and wire the two contexts by domain events across the boundary. Split a domain that has grown to hold two languages, break a circular cluster dependency, or remove cross-aggregate references that reach across a seam. The owning context publishes an event; the other consumes it through a subscriber and an anti-corruption layer, holding the far side by identity. Use when the user asks to "extract a bounded context", "split a domain", "pull these aggregates into their own context", "break a circular dependency between aggregates", "separate sales from fulfilment", "introduce a second bounded context", or when they describe one domain that has grown two distinct languages.
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [add-subscriber-flow, event, aggregate]
  diagnostic_codes: [CIRCULAR_CLUSTER_DEPENDENCY]
---

# Extract Bounded Context

In Protean each `Domain` is a bounded context. When one domain grows to hold two
languages, that is a sign it holds two contexts that belong apart. This skill
takes a set of aggregates out of one `Domain` into a second `Domain` and wires
the two by domain events across the boundary.

It builds on the element skills [add-subscriber-flow](../add-subscriber-flow/SKILL.md)
for the anti-corruption layer, [event](../event/SKILL.md) for the cross-context
event, and [aggregate](../aggregate/SKILL.md) for the aggregates on each side.

## When to reach for this

`check` reports the smells that push toward the split:

- `CIRCULAR_CLUSTER_DEPENDENCY`: two aggregate clusters hold identity references
  at each other, forming a cycle. Neither can be loaded or changed on its own.
- `CROSS_AGGREGATE_REFERENCE`: a `Reference` from one aggregate reaches across
  what should be a boundary into a different aggregate's root.

A handful of these between two groups of aggregates is a seam. The
[seam-detection reference](references/seam-detection.md) covers the signals and
how to sort each aggregate onto its side.

## Worked example: sales and fulfilment

One domain holds both a sales context and a fulfilment context. `Order` (sales)
points at its `Shipment` and `Shipment` (fulfilment) points back at its `Order`,
both by `Reference`. Those two cross-cluster references form a cycle, so `check`
reports `CIRCULAR_CLUSTER_DEPENDENCY` on both clusters.

[extract_bounded_context_before.py](assets/extract_bounded_context_before.py) is
the tangled starting point. [extract_bounded_context_after.py](assets/extract_bounded_context_after.py)
is the extraction: two `Domain` objects that talk by a published event across the
seam, with the cycle gone.

## Recipe

### 1. Detect the seam

Run `check` and read the `CIRCULAR_CLUSTER_DEPENDENCY` and
`CROSS_AGGREGATE_REFERENCE` findings. They name the aggregates that reference
each other across the boundary. Group the aggregates by the language they speak:
`Order` and `Payment` are sales; `Shipment` and `Manifest` are fulfilment. Each
reference that crosses the seam is a line in the rewrite work list. See the
[seam-detection reference](references/seam-detection.md).

### 2. Stand up the second context

Create a second `Domain` for the aggregates you are extracting, and move them and
their events, commands, and handlers into it:

```python
fulfilment = Domain(name="Fulfilment")


@fulfilment.aggregate
class Shipment:
    order_id = Identifier(required=True)
    address = String(required=True, max_length=200)
    status = String(default="pending", max_length=20)
```

The moved aggregate holds the far side by its identifier (`order_id`), a plain
`Identifier` field. That identity is what replaces the `Reference` that used to
cross the seam.

### 3. Rewire the seam with events

Replace each cross-seam reference with a domain event. The owning context
publishes the event as part of its published language, and turns the outbox on so
the event actually leaves the context:

```python
sales.config["server"]["default_subscription_type"] = "stream"
sales.config["brokers"]["events"] = {"provider": "inline"}
sales.config["outbox"]["external_brokers"] = ["events"]


@sales.event(part_of="Order", published=True)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    address = String(required=True)
```

The other context consumes the event through a subscriber that translates it into
its own command. The subscriber is the anti-corruption layer. It listens on the
publishing aggregate's `stream_category`, and the fields sit under `payload["data"]`:

```python
@fulfilment.subscriber(stream="sales::order")
class OrderPlacedSubscriber:
    def __call__(self, payload: dict) -> None:
        if payload["metadata"]["headers"]["type"] != OrderPlaced.__type__:
            return
        data = payload["data"]
        fulfilment.process(
            CreateShipment(order_id=data["order_id"], address=data["address"])
        )
```

The [event-integration reference](references/event-integration.md) covers
`published=True`, the outbox and `outbox.external_brokers` wiring, the stream and
envelope the outbox delivers on, and holding the far side by identity in full.

## What the extraction clears

Once the two contexts hold each other by identity and talk by events, neither
holds a `Reference` into the other. The cycle is gone, so `check` reports neither
`CIRCULAR_CLUSTER_DEPENDENCY` nor `CROSS_AGGREGATE_REFERENCE` on either domain.

## Related skills

- [add-subscriber-flow](../add-subscriber-flow/SKILL.md): the subscriber and
  anti-corruption layer that consume the cross-context event.
- [event](../event/SKILL.md): the domain event published across the seam.
- [aggregate](../aggregate/SKILL.md): the aggregates on each side of the split.
- [refactor-introduce-events](../refactor-introduce-events/SKILL.md): the
  in-context step of replacing direct calls with events, before a seam appears.

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and
  resolve what it reports, including any `CIRCULAR_CLUSTER_DEPENDENCY`.
