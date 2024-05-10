from protean import Domain
from protean.fields import String

domain = Domain(__file__)


@domain.aggregate
class Person:
    name = String(required=True)
    email = String(unique=True)
