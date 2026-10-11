from protean import Domain
from protean.fields import Identifier, String

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="DRAFT")


# --8<-- [start:template]
def placed_order():
    order = Order({"customer_id": "c-1", "status": "DRAFT"}, status="PLACED")
    return order


# --8<-- [end:template]


# --8<-- [start:catch]
def build_order(payload):
    try:
        order = Order(payload)
    except TypeError:
        order = None
    return order


# --8<-- [end:catch]
