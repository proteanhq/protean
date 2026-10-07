from protean import Domain
from protean.fields import String

domain = Domain(name="Customers")


# --8<-- [start:aggregate]
from protean import Index


@domain.aggregate(
    indexes=[
        Index("email", unique=True),
        Index("status"),
    ]
)
class Customer:
    email = String(max_length=255, required=True)
    status = String(max_length=32, default="active")


# --8<-- [end:aggregate]
