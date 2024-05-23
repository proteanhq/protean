from protean import Domain
from protean.fields import Integer, String

domain = Domain(__file__)


@domain.aggregate
class Person:
    name = String(required=True, min_length=3, max_length=50)
    age = Integer(required=True, min_value=0, max_value=120)
