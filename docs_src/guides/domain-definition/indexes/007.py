from protean import Domain, Index, Q
from protean.fields import Integer, String

domain = Domain(name="Tasks")


# --8<-- [start:aggregate]
ACTIVE_TASKS = Index(
    "status",
    "priority",
    desc=("priority",),
    where=Q(status__in=["pending", "failed"]),
    name="ix_active",
)


@domain.aggregate(indexes=[ACTIVE_TASKS, Index("correlation_id")])
class Task:
    status = String(max_length=32)
    priority = Integer(default=0)
    correlation_id = String(max_length=64)


# --8<-- [end:aggregate]
