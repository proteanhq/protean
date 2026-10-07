from protean import Domain
from protean.fields import String

domain = Domain(name="People")


# --8<-- [start:aggregate]
@domain.aggregate
class Person:
    name: String(required=True, referenced_as="full_name")
    email: String()


# --8<-- [end:aggregate]
