# Finding the seam

Two rules decide where to cut an oversized aggregate. Linking the two halves
afterwards, by identity and a domain event, is covered in the skill itself.

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
The two groups start, change and end at different times, so they are two
lifecycles and two aggregates.
