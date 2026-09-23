# Finding the seam

Extraction starts by finding the boundary that is already there in the code.
Extraction names it and makes it explicit. Three signals point at it.

## The signals

### A circular cluster dependency

Two aggregate clusters hold identity references at each other, forming a cycle.
`Order` points at its `Shipment`, `Shipment` points back at its `Order`. `check`
reports this as `CIRCULAR_CLUSTER_DEPENDENCY`, once per cluster in the cycle.

A cycle means neither cluster can be understood, loaded, or changed on its own.
That is the clearest sign the two belong in separate contexts. Each one wants to
own its side and hear about the other's changes across a boundary.

### A cross-aggregate reference

Even without a full cycle, a `Reference` from one aggregate to a different
aggregate's root reaches across what should be a boundary. `check` reports it as
`CROSS_AGGREGATE_REFERENCE`. One such reference is a smell inside a single
context; a cluster of them between two groups of aggregates is a seam.

### Two languages

The strongest signal is not in the code. When the same word means two things,
you have two contexts. An "order" in sales is a customer's intent to buy; an
"order" in fulfilment is a picking-and-packing job. When one team says "ship" and
the other says "dispatch" for the same act, or when a field matters to one group
and is dead weight to the other, the boundary is already drawn in the language.

## Sorting the aggregates

Once you see the seam, sort each aggregate onto one side of it. Ask which
context's language owns the aggregate and which context changes it. `Order`,
`Cart`, and `Payment` speak sales; `Shipment`, `Pick`, and `Manifest` speak
fulfilment. An aggregate that seems to belong to both is usually two aggregates
wearing one name, and the split is the moment to separate them.

The references crossing the seam are the work list for the rewrite. Each one
becomes an event published by the owning context and consumed by the other. See
[event integration across the seam](event-integration.md).
