from protean import Domain, handle
from protean.fields import Decimal, HasMany, Identifier, Integer, String

domain = Domain(name="Ordering")


# --8<-- [start:derive]
from protean import value_object_from_entity
from protean.fields import List


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()
    unit_price: Decimal(precision=19, scale=4)
    internal_notes: String(max_length=500)


# Auto-generate a VO mirroring OrderItem's fields
OrderItemVO = value_object_from_entity(OrderItem)
# --8<-- [end:derive]

# --8<-- [start:custom]
OrderItemVO = value_object_from_entity(
    OrderItem,
    name="OrderItemPayload",
    exclude={"internal_notes"},
)
# --8<-- [end:custom]


# --8<-- [start:command]
from protean.fields import ValueObjectFromEntity


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)
    items: List(content_type=ValueObjectFromEntity(OrderItem))


# --8<-- [end:command]


# --8<-- [start:handler]
@domain.command_handler(part_of=Order)
class PlaceOrderHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        items = [OrderItem.from_value_object(item) for item in command.items]
        order = Order(customer_id=command.customer_id, items=items)
        return order


# --8<-- [end:handler]
