from protean import Domain
from protean.fields import List, String

domain = Domain(__file__)


@domain.aggregate
class Building:
    permit = List(
        content_type=String, description="Licences and Approvals", required=True
    )
