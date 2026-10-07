from protean import Domain
from protean.fields import String, ValueObject

domain = Domain(name="Customers")


# --8<-- [start:aggregate]
@domain.value_object
class Address:
    street: String(max_length=200)
    city: String(max_length=100)
    zip_code: String(max_length=10)


@domain.aggregate
class Customer:
    name: String(max_length=100)
    billing_address = ValueObject(Address)


# --8<-- [end:aggregate]
