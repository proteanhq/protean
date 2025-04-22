from protean import Domain
from protean.fields import Integer, String

domain = Domain()


@domain.event_sourced_aggregate
class Person:
    name = String()
    age = Integer()
