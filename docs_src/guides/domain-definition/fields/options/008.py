from protean import Domain
from protean.fields import String

domain = Domain(__file__)


@domain.aggregate
class Person:
    email = String(unique=True)
    name = String(referenced_as="fullname", required=True)
