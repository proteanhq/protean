# --8<-- [start:aggregate]
from protean import Domain
from protean.fields import String

domain = Domain(name="Sales")


@domain.aggregate
class Customer:
    name: String(max_length=100, required=True)


# --8<-- [end:aggregate]
