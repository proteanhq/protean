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

from protean.utils.query import F, Q


def claim(dao, message, worker_id, now):
    # Simplified view of the per-message compare-and-swap inside _claim().
    # A row is eligible when it is pending, failed, or processing under an
    # expired lock, its lock is free, its retry time is due, and it has
    # retries left:
    eligible = (
        Q(id=message.id, status__in=["pending", "failed", "processing"])
        & (Q(locked_until__isnull=True) | Q(locked_until__lte=now))
        & (Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
        & Q(retry_count__lt=F("max_retries"))
    )
    claimed_count = dao._update_all(
        eligible,
        {
            "status": "processing",
            "locked_by": worker_id,
            "locked_until": now + timedelta(minutes=5),
            "last_processed_at": now,
        },
    )
    # claimed_count > 0 only for the winning worker
    return claimed_count


# --8<-- [end:claim]
