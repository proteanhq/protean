from protean import Domain
from protean.fields import Auto, Identifier, String

domain = Domain(name="RenameAfter")


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)


# --8<-- [start:after]
# After: `name` becomes `customer_name`
@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_name = String(required=True, renamed_from="name")


# --8<-- [end:after]
