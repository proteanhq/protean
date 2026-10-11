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


# --8<-- [start:persist]
domain.init(traverse=False)

with domain.domain_context():
    order = Order(number="ORD-1", items=[OrderItem(product_name="Widget", quantity=2)])

    repo = domain.repository_for(Order)
    repo.add(order)  # Persists the order AND all its OrderItems
# --8<-- [end:persist]

# --8<-- [start:navigation]
with domain.domain_context():
    # Access parent aggregate from entity
    order_item = order.items[0]
    parent_order = order_item.order  # Order object
    order_id = order_item.order_id  # Order's ID value
# --8<-- [end:navigation]
