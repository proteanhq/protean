# --8<-- [start:full]
from protean import Domain
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class Person:
    name: String(max_length=255)
    age: Integer(required=True)


# --8<-- [end:full]
