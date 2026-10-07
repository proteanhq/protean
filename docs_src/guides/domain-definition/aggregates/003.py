from protean import Domain
from protean.fields import String

domain = Domain(name="Sales")


# --8<-- [start:aggregate]
@domain.aggregate(fact_events=True)
class Customer:
    name: String(max_length=100)
    email: String(max_length=255)


# --8<-- [end:aggregate]
