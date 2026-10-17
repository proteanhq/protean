from protean import Domain
from protean.fields import Auto, Identifier

domain = Domain(name="EventIdentifiers")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)


# --8<-- [start:identifiers]
@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)  # This aggregate
    customer_id: Identifier(required=True)  # Referenced aggregate
    shipping_address_id: Identifier()  # Referenced aggregate


# --8<-- [end:identifiers]
