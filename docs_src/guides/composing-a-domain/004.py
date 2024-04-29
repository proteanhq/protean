from protean import Domain
from protean.fields import Integer, String, ValueObject

domain = Domain(__file__)


@domain.value_object
class Address:
    address1 = String(max_length=255, required=True)
    address2 = String(max_length=255)
    address3 = String(max_length=255)
    city = String(max_length=25, required=True)
    state = String(max_length=25, required=True)
    country = String(max_length=2, required=True)
    zip = String(max_length=6, required=True)


@domain.aggregate
class User:
    first_name = String(max_length=50)
    last_name = String(max_length=50)
    age = Integer()
    address = ValueObject(Address)
