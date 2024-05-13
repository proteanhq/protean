from protean import Domain
from protean.fields import Integer, String

domain = Domain(__file__)


@domain.aggregate
class Person:
    name = String(max_length=255)
    age = Integer(required=True)
