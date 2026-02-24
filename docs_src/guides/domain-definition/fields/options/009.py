# --8<-- [start:full]
from protean import Domain
from protean.fields import List, String

domain = Domain()


@domain.aggregate
class Building:
    permit: List(
        content_type=String, description="Licences and Approvals", required=True
    )


# --8<-- [end:full]
