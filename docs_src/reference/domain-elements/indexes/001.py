# --8<-- [start:aggregate]
from protean import Domain, Index, Q
from protean.fields import Integer, String

domain = Domain(name="Ordering")


@domain.aggregate(
    indexes=[
        Index("status", "priority", desc=("priority",)),
        Index("email", unique=True),
        Index("status", where=Q(status__in=["pending", "failed"]), name="ix_active"),
    ]
)
class Order:
    email: String(max_length=254)
    status: String(max_length=20)
    priority: Integer()


# --8<-- [end:aggregate]
