from protean import Domain
from protean.fields import Dict, String

domain = Domain(__file__, load_toml=False)


@domain.aggregate
class UserEvent:
    name = String(max_length=255)
    payload = Dict()
