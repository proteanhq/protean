from protean import Domain
from protean.fields import String

domain = Domain(name="Tasks")


# --8<-- [start:aggregate]
from protean import Index, Q


@domain.aggregate(
    indexes=[
        Index("status", where=Q(status__in=["pending", "failed"]), name="ix_active"),
    ]
)
class Task:
    status = String(max_length=32)


# --8<-- [end:aggregate]
