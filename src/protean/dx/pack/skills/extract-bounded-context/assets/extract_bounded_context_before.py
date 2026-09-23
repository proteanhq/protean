"""
One domain holding two bounded contexts that reference each other in a cycle
(before extraction).

Sales and fulfilment live in a single `Domain`. `Order` (sales) points at its
`Shipment` and `Shipment` (fulfilment) points back at its `Order`, both by
in-process `Reference` identity fields. Those two cross-cluster references form a
directed cycle, so `check` reports `CIRCULAR_CLUSTER_DEPENDENCY` on both clusters
(and `CROSS_AGGREGATE_REFERENCE` on each reference).

The fix is to split the two contexts into separate `Domain` objects that talk by
domain events across the seam. See extract_bounded_context_after.py.
"""

from protean import Domain
from protean.fields import Reference, String

domain = Domain(__name__)


# --- Sales context ---


@domain.aggregate
class Order:
    customer_id = String(required=True, max_length=50)
    status = String(default="placed", max_length=20)
    # Points across the seam into fulfilment. Half of the cycle.
    shipment = Reference("Shipment")


# --- Fulfilment context ---


@domain.aggregate
class Shipment:
    address = String(required=True, max_length=200)
    status = String(default="pending", max_length=20)
    # Points back across the seam into sales. The other half of the cycle.
    order = Reference("Order")


if __name__ == "__main__":
    domain.init(traverse=False)
    # Run `protean check` against this module to see the diagnostic:
    #   CIRCULAR_CLUSTER_DEPENDENCY  Order <-> Shipment reference each other
