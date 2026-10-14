from protean import Domain
from protean.fields import Float, Identifier

domain = Domain(
    name="Shop",
    config={"server": {"default_subscription_type": "stream"}},
)


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    total: Float(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    total: Float(required=True)


# --8<-- [start:claim]
from datetime import timedelta

from protean.utils.query import Q


def claim(dao, message, worker_id, now):
    # Simplified view of the per-message compare-and-swap inside _claim():
    claimed_count = dao._update_all(
        Q(id=message.id, status__in=["pending", "failed"]),  # Only eligible messages
        {
            "status": "processing",
            "locked_by": worker_id,
            "locked_until": now + timedelta(minutes=5),
        },
    )
    # claimed_count > 0 only for the winning worker
    return claimed_count


# --8<-- [end:claim]
