from protean import Domain
from protean.fields import String

domain = Domain(name="Sales")


# --8<-- [start:aggregate]
@domain.aggregate
class Customer:
    email: String(required=True)
    name: String(max_length=100)


# --8<-- [end:aggregate]
