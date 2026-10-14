# ruff: noqa: B018
from protean import Domain

domain = Domain(name="ShadowFields")

# isort: split

# --8<-- [start:value_object]
from protean.core.value_object import BaseValueObject
from protean.fields import String, ValueObject


class Address(BaseValueObject):
    street: String(max_length=200)
    city: String(max_length=100)
    zip_code: String(max_length=10)


@domain.aggregate
class Customer:
    name: String(max_length=100, required=True)
    billing_address: ValueObject(Address)


# --8<-- [end:value_object]


# --8<-- [start:reference]
from protean.fields import Reference, String


@domain.aggregate
class Order:
    placed_by: String(max_length=100)


@domain.entity(part_of="Order")
class LineItem:
    description: String(max_length=200)
    order = Reference("Order")


# --8<-- [end:reference]

# --8<-- [start:extraction]
with domain.domain_context():
    customer = Customer(
        name="Alice",
        billing_address_street="123 Main",  # Extracted as shadow kwarg
        billing_address_city="NYC",  # Extracted as shadow kwarg
        billing_address_zip_code="10001",  # Extracted as shadow kwarg
    )
# --8<-- [end:extraction]

# --8<-- [start:equivalent]
# These two are equivalent:
with domain.domain_context():
    Customer(
        name="Alice",
        billing_address=Address(street="123 Main", city="NYC", zip_code="10001"),
    )
    Customer(
        name="Alice",
        billing_address_street="123 Main",
        billing_address_city="NYC",
        billing_address_zip_code="10001",
    )
# --8<-- [end:equivalent]

# --8<-- [start:assignment]
customer.billing_address = Address(street="456 Oak", city="LA", zip_code="90001")
# Automatically sets:
#   customer.__dict__["billing_address_street"] = "456 Oak"
#   customer.__dict__["billing_address_city"] = "LA"
#   customer.__dict__["billing_address_zip_code"] = "90001"
# --8<-- [end:assignment]

# --8<-- [start:direct_access]
customer.billing_address_street  # "456 Oak"
customer.billing_address_street = "789 Pine"  # Updates shadow, marks entity as changed
# --8<-- [end:direct_access]

# --8<-- [start:attributes]
from protean.utils.reflection import attributes

attributes(Customer)
# Returns: {
#   "name": <ResolvedField for name>,
#   "id": <ResolvedField for id>,
#   "billing_address_street": <_ShadowField for street>,
#   "billing_address_city": <_ShadowField for city>,
#   "billing_address_zip_code": <_ShadowField for zip_code>,
#   "_version": <ResolvedField for _version>,
# }
# --8<-- [end:attributes]

domain.init(traverse=False)
