from protean import Domain
from protean.fields import Dict, String

domain = Domain(__file__)


@domain.aggregate
class UserEvent:
    name = String(max_length=255)
    payload = Dict()
