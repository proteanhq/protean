from protean import Domain
from protean.fields import Identifier

domain = Domain(name="ecommerce")


# --8<-- [start:order]
# Your aggregate definition
@domain.aggregate
class Order: ...


# Internally becomes: "ecommerce::order"
# Where "ecommerce" is your domain name
# --8<-- [end:order]


# --8<-- [start:default_names]
@domain.aggregate
class User: ...


# Stream category: "user"


@domain.aggregate
class OrderItem: ...


# Stream category: "order_item"
# --8<-- [end:default_names]


# --8<-- [start:command]
@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(required=True)
    # Routes to Order's stream category


# --8<-- [end:command]
