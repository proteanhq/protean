---
name: split-aggregate
description: Split an oversized aggregate into two along its consistency boundary. Detects an aggregate that has grown two concerns and too many entities, extracts the second concern into its own aggregate, links the two by identity, and carries the cross-aggregate step with a domain event. Use when the user says "split this aggregate", "my aggregate is too big", "extract an aggregate", "aggregate has too many entities", "AGGREGATE_TOO_LARGE", "CROSS_AGGREGATE_REFERENCE", "one aggregate two concerns", "break up a large aggregate", or when an audit reports an aggregate over the size limit or a reference that crosses an aggregate boundary.
license: Apache-2.0
compatibility: "Requires Python 3.11+, protean framework"
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [aggregate, refactor-move-logic-to-aggregate, event, domain-service]
  diagnostic_codes: [AGGREGATE_TOO_LARGE, CROSS_AGGREGATE_REFERENCE]
---

# Split Aggregate

> **Illustrative, guided refactoring.** This is a before→after walkthrough.
> Recognize the smell, pick the seam yourself, and apply the change by hand; the
> framework does not transform the code for you. The `split_order_before.py`
> asset is the oversized starting point; `split_order_after.py` is the target.

An aggregate should hold one consistency boundary. When it grows a second
concern, with its own entities and its own lifecycle, the cluster gets large and
`check` reports `AGGREGATE_TOO_LARGE`: it counts more child entities in one
cluster than `[lint] aggregate_size_limit` allows (default five). That count is
the signal to split.

## Before: one aggregate, two concerns

[split_order_before.py](assets/split_order_before.py) is an `Order` that carries
both the order concern (items, discounts, gift wraps) and the fulfilment concern
(packages, tracking events, delivery attempts). Six child entities in one
cluster, over the default limit of five, so `check` reports it:

```
AGGREGATE_TOO_LARGE  Aggregate `Order` has 6 entities (limit: 5)
```

## Pick the seam

The seam is the invariant boundary. Read the entities and group the ones that
must stay consistent together in one transaction. In the Order example, the
order concern is one such group and the fulfilment concern is another. A change
to a tracking event can commit on its own without a discount changing at the
same time, so they are two boundaries and belong in two aggregates.

When the boundary is unclear, use lifecycle as the tiebreak: state that is
created, changed, and retired on a different schedule is a second aggregate. The
[finding-the-seam](references/finding-the-seam.md) reference covers both rules in
full.

## After: two aggregates, linked by identity and an event

[split_order_after.py](assets/split_order_after.py) extracts the fulfilment
concern into a `Shipment` aggregate. Each cluster now holds three entities, under
the limit, so `AGGREGATE_TOO_LARGE` is gone.

### 1. Move the second concern into its own aggregate

Create the new aggregate and move the extracted entities under it with
`part_of`. The entity classes are unchanged; only their parent changes.

```python
@domain.aggregate
class Shipment:
    order_id: Identifier(required=True)   # identity link back to Order
    status: String(default="pending")

    packages = HasMany("Package")
    tracking_events = HasMany("TrackingEvent")
    delivery_attempts = HasMany("DeliveryAttempt")
```

### 2. Link by identity

`Shipment` names the order it fulfils by holding the order's id in a plain
`Identifier` field. Holding a `Reference` to the `Order` root would reach across
the boundary, which is what `check` reports as `CROSS_AGGREGATE_REFERENCE`:

```python
# Wrong: a Reference across an aggregate boundary re-couples the two clusters.
order = Reference("Order")
```

The identity field carries the link and keeps the two aggregates as separate
loading and locking units. Load the `Order` through its own repository when a
`Shipment` needs it.

### 3. Carry the cross-aggregate step with a domain event

The two aggregates commit in separate transactions, so the step that spans them
happens as two writes joined by an event. `Order` raises `OrderPlaced` when it is
placed. An event handler in `Order`'s own cluster reacts and issues an
`OpenShipment` command, and `Shipment`'s command handler opens the shipment.

```python
@domain.event_handler(part_of=Order)
class ShipmentInitiation:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        current_domain.process(OpenShipment(order_id=event.order_id))
```

The handler stays in `Order`'s cluster because it reacts to `Order`'s own event.
A handler that reacts to another cluster's event trips
`EVENT_HANDLER_FOREIGN_EVENT`; for a flow with several causally dependent steps,
reach for a process manager. See [event](../event/SKILL.md) for raising the event
and [domain-service](../domain-service/SKILL.md) for a step whose logic spans
both aggregates.

## Common mistakes

1. **Cut on the consistency boundary, wherever it falls.** Two entities that must
   stay correct together in one transaction stay in one aggregate, however large
   the cluster grows.

2. **Do not link the new aggregate back with a `Reference`.** A `Reference` to
   the other root re-couples the clusters and brings back
   `CROSS_AGGREGATE_REFERENCE`. Hold the other aggregate's id by value.

3. **Keep the event handler in the cluster that owns the event.** A handler that
   reacts to another cluster's event trips `EVENT_HANDLER_FOREIGN_EVENT`. Hand
   off to the other aggregate with a command.

## Related skills

- [aggregate](../aggregate/SKILL.md): the aggregate and its consistency boundary.
- [refactor-move-logic-to-aggregate](../refactor-move-logic-to-aggregate/SKILL.md):
  the companion refactor for logic that has leaked out of an aggregate.
- [event](../event/SKILL.md): the domain event that links the two aggregates.
- [domain-service](../domain-service/SKILL.md): for business logic that spans two
  aggregates once they are split.

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and
  resolve what it reports, including any `AGGREGATE_TOO_LARGE` or
  `CROSS_AGGREGATE_REFERENCE`.
