from protean import Domain, Index
from protean.fields import Integer, String

domain = Domain(name="Jobs")


# --8<-- [start:aggregate]
@domain.aggregate(
    indexes=[
        Index("status", "priority", desc=("priority",)),
    ]
)
class Job:
    status = String(max_length=32)
    priority = Integer(default=0)


# --8<-- [end:aggregate]
