# --8<-- [start:setup]
from protean import Domain
from protean.fields import Float, Identifier, String

domain = Domain(name="Shop")
# --8<-- [end:setup]


# --8<-- [start:before]
# Before (CQRS)
@domain.aggregate
class Order:
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float()


# --8<-- [end:before]
