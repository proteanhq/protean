from protean import Domain, Index, Q

domain = Domain(name="IndexedTickets")

# --8<-- [start:ticket]
from protean.fields import DateTime, Identifier, String


@domain.aggregate(
    indexes=[
        # uniqueness invariant
        Index("email", unique=True),
        # foreign lookup
        Index("organization_id"),
        # filter + sort, over the hot subset only
        Index(
            "status",
            "created_at",
            desc=("created_at",),
            where=Q(status="open"),
            name="ix_open",
        ),
    ]
)
class Ticket:
    email = String(max_length=255, required=True)
    organization_id = Identifier(required=True)
    status = String(max_length=32, default="open")
    created_at = DateTime()


# --8<-- [end:ticket]

domain.init(traverse=False)
