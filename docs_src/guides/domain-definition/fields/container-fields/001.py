from protean import Domain
from protean.fields import List, String

domain = Domain(__file__)


@domain.aggregate
class User:
    email = String(max_length=255, required=True, unique=True)
    roles = List()
