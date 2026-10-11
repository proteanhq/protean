from protean import Domain
from protean.fields import HasMany, Integer, String

domain = Domain()


@domain.aggregate
class Order:
    number: String(max_length=20)
    items = HasMany("OrderItem")


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)
    quantity: Integer()


# --8<-- [start:place_order]
from protean import handle
from protean.fields import List, ValueObjectFromEntity


@domain.command(part_of=Order)
class PlaceOrder:
    number: String(max_length=20)
    items: List(content_type=ValueObjectFromEntity(OrderItem))


@domain.command_handler(part_of=Order)
class PlaceOrderHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        items = [OrderItem.from_value_object(item) for item in command.items]
        order = Order(number=command.number, items=items)
        domain.repository_for(Order).add(order)


# --8<-- [end:place_order]

# --8<-- [start:conversion]
from protean import value_object_from_entity

OrderItemData = value_object_from_entity(OrderItem)

with domain.domain_context():
    data = OrderItemData(product_name="Widget", quantity=2)
    item = OrderItem.from_value_object(data)
    print(item.product_name, item.quantity)  # Widget 2
# --8<-- [end:conversion]
