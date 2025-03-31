from protean import Domain
from protean.fields import Integer, String

domain = Domain(__file__)


@domain.event_sourced_aggregate
class Person:
    name = String()
    age = Integer()
