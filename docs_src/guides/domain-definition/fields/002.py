from protean import Domain
from protean.fields import String

domain = Domain(__file__)


@domain.aggregate
class Person:
    email = String(identifier=True)
    name = String(required=True)
