from protean import Domain
from protean.fields import Boolean, String

domain = Domain(__file__, load_toml=False)


@domain.aggregate
class User:
    name = String(required=True)
    subscribed = Boolean(default=False)
