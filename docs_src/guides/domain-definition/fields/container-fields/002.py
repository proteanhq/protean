from protean import Domain
from protean.fields import Dict, String

domain = Domain()


@domain.aggregate
class UserEvent:
    name: String(max_length=255)
    payload: Dict()
