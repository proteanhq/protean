from protean import Domain
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class Person:
    name = String(required=True, max_length=50)
    age = Integer(default=21)
    country = String(max_length=2)
