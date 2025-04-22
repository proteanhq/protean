from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Person:
    email = String(identifier=True)
    name = String(required=True)
