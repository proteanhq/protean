from protean import Domain
from protean.fields import Integer, String

domain = Domain(name="Ordering")

# --8<-- [start:aggregate]
from protean import Index, Q


@domain.aggregate(
    indexes=[
        Index("email", unique=True),
        Index(
            "status",
            "priority",
            desc=("priority",),
            where=Q(status__in=["pending", "failed"]),
            name="ix_active",
        ),
    ]
)
class Order:
    email = String(max_length=255, required=True)
    status = String(max_length=32, default="pending")
    priority = Integer(default=0)


# --8<-- [end:aggregate]
