from protean import Domain
from protean.fields import String

domain = Domain(__file__, load_toml=False)


@domain.aggregate
class Person:
    name = String(required=True, min_length=2, max_length=50, sanitize=True)
