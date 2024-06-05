from protean import Domain
from protean.fields import List, String

domain = Domain(__file__, load_toml=False)


@domain.aggregate
class User:
    email = String(max_length=255, required=True, unique=True)
    roles = List()
