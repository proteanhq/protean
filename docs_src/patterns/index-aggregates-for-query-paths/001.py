from protean import Domain

domain = Domain(name="IndexedOutbox")

# --8<-- [start:outbox]
from protean import Index, Q
from protean.fields import Integer, String


@domain.aggregate(
    indexes=[
        Index(
            "status",
            "priority",
            desc=("priority",),
            where=Q(status__in=["pending", "failed"]),
            name="ix_active",
        ),
        Index("message_id", unique=True),
        Index("correlation_id"),
    ]
)
class Outbox:
    message_id = String(max_length=255, required=True)
    status = String(max_length=32, default="pending")
    priority = Integer(default=0)
    correlation_id = String(max_length=255)


# --8<-- [end:outbox]


domain.init(traverse=False)
