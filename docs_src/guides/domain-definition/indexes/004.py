from protean import Domain, Index
from protean.fields import Integer, String

domain = Domain(name="Jobs")


# --8<-- [start:aggregate]
@domain.aggregate(
    indexes=[
        Index("status", include=("priority",), name="ix_status_cover"),
    ]
)
class Job:
    status = String(max_length=32)
    priority = Integer()


# --8<-- [end:aggregate]
