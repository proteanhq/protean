# Finding the seam

Splitting an aggregate is a modelling decision. The hard part is picking where
to cut. These are the rules to cut by.

## The seam is the invariant boundary

An aggregate exists to hold one consistency boundary: the set of fields and
entities that must stay correct together, in one transaction. When you find two
such boundaries inside one aggregate, that is the seam.

In the Order example, two boundaries share one aggregate:

- The order concern: items, discounts, gift wraps. What the customer ordered and
  what it costs.
- The fulfilment concern: packages, tracking events, delivery attempts. How the
  goods physically move.

A change to a tracking event can commit on its own, in its own transaction,
without a discount changing at the same time. They are two boundaries, so they
are two aggregates. Cut along that line.

## Lifecycle is the tiebreak

When the invariant boundary is unclear, look at lifecycle. Two groups of state
that are created at different times, change on different triggers, and are
retired at different points belong to two aggregates.

An order is placed once and then mostly settles. Its shipment is opened later,
moves through a series of carrier updates, and is closed when the goods arrive.
Different birth, different cadence, different end. That is a second lifecycle,
and a second aggregate.

## Link by identity

Once the two aggregates are separate, one still needs to name the other. Do it
by identity: store the other aggregate's id in a plain field.

```python
@domain.aggregate
class Shipment:
    order_id: Identifier(required=True)   # the Order's id, held by value
```

Avoid a `Reference` field pointing at the other aggregate's root:

```python
# Wrong: a Reference across an aggregate boundary.
order = Reference("Order")
```

A `Reference` across aggregates is what `check` reports as
CROSS_AGGREGATE_REFERENCE. It couples the two clusters and pulls them back into
one loading and locking unit, which is the coupling the split was meant to undo.
Hold the id, and load the other aggregate through its own repository when you
need it.

## Carry the cross-aggregate step with a domain event

The two aggregates commit in separate transactions, so a step that spans both
has to happen as two writes. Carry it with a domain event: one aggregate raises
the event on its state change, and a handler reacts and drives the other
aggregate through a command. That keeps the link one-directional and decoupled,
and it never reintroduces a direct object reference.
