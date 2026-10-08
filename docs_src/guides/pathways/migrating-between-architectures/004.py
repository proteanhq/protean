from protean import Domain
from protean.fields import Float, Identifier, String

domain = Domain(name="Shop")


# --8<-- [start:after]
# After (Event Sourcing)
@domain.aggregate(event_sourced=True)
class Order:
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float()


# --8<-- [end:after]
