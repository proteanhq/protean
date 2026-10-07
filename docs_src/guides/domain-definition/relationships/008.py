from protean import Domain
from protean.fields import HasMany, Identifier, String, ValueObject

domain = Domain(name="Ordering")


# --8<-- [start:aggregates]
@domain.aggregate
class Order:
    customer_id = Identifier(required=True)  # References Customer aggregate
    items = HasMany("OrderItem")


@domain.aggregate
class Customer:
    name: String(max_length=100)
    email = ValueObject("Email")


@domain.value_object
class Email:
    address: String(max_length=254, required=True)


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(max_length=100)


# --8<-- [end:aggregates]


# --8<-- [start:load]
domain.init(traverse=False)

with domain.domain_context():
    jane = Customer(name="Jane", email=Email(address="jane@example.com"))
    domain.repository_for(Customer).add(jane)
    order = Order(customer_id=jane.id)

    customer = domain.repository_for(Customer).get(order.customer_id)
# --8<-- [end:load]
