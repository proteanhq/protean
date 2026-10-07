from protean import Domain
from protean.fields import Float, Identifier, String

domain = Domain(name="Ordering")


# --8<-- [start:renamed_from]
@domain.aggregate
class Order:
    order_id = Identifier(identifier=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(identifier=True)
    customer_name = String(renamed_from="name")  # single old name
    total = Float(renamed_from=["amount", "sum"])  # or a list of aliases


# --8<-- [end:renamed_from]
