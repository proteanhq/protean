from protean import Domain
from protean.fields import HasOne, List, String, ValueObject

domain = Domain(__file__)


@domain.value_object
class Address:
    street = String(max_length=100)
    city = String(max_length=25)
    state = String(max_length=25)
    country = String(max_length=25)


@domain.entity(part_of="Order")
class Customer:
    name = String(max_length=50, required=True)
    email = String(max_length=254, required=True)
    addresses = List(content_type=ValueObject(Address))


@domain.aggregate
class Order:
    customer = HasOne(Customer)
