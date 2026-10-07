from protean import Domain, handle
from protean.exceptions import ValidationError
from protean.fields import Auto, Float, HasMany, Identifier, Integer, List, String
from protean.utils.globals import current_domain

domain = Domain(name="SmallAggregatesIdentity")
domain.config["command_processing"] = "sync"


# --8<-- [start:order]
# Pattern: Order references Customer by identity
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)  # Just the identity
    items = HasMany("OrderItem")
    status: String(default="pending")
    total: Float(default=0.0)


# --8<-- [end:order]


@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)


# --8<-- [start:command]
@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    customer_name: String(required=True)  # Included by the caller
    customer_email: String(required=True)  # Included by the caller
    items: List(required=True)


# --8<-- [end:command]


@domain.projection
class CustomerCreditView:
    customer_id: Identifier(identifier=True)
    credit_status: String(default="active")


# --8<-- [start:read_model]
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # Check customer's credit status via a read model
        customer_view = current_domain.repository_for(CustomerCreditView).get(
            command.customer_id
        )

        if customer_view.credit_status == "suspended":
            raise ValidationError({"customer_id": ["Customer credit is suspended"]})

        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            items=command.items,
        )
        current_domain.repository_for(Order).add(order)


# --8<-- [end:read_model]
