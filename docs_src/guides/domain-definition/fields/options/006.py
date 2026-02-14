from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Person:
    name = String(required=True)
    email = String(unique=True)
