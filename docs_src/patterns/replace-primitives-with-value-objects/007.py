from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, String, ValueObject

domain = Domain(name="AddressValueObject")


# --8<-- [start:address]
@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)
    country: String(max_length=2, required=True)

    @invariant.post
    def country_must_be_iso_code(self):
        if len(self.country) != 2 or not self.country.isalpha():
            raise ValidationError({"country": ["Country must be a 2-letter ISO code"]})


@domain.aggregate
class Customer:
    customer_id: Auto(identifier=True)
    name: String(required=True)
    shipping_address = ValueObject(Address)
    billing_address = ValueObject(Address)


# --8<-- [end:address]


# --8<-- [start:usage]
def register_customer():
    customer = Customer(
        name="Jane Smith",
        shipping_address=Address(
            street="123 Main St",
            city="Springfield",
            state="IL",
            postal_code="62701",
            country="US",
        ),
        billing_address=Address(
            street="456 Oak Ave",
            city="Chicago",
            state="IL",
            postal_code="60601",
            country="US",
        ),
    )
    return customer


# --8<-- [end:usage]


# --8<-- [start:replace]
def move_customer(customer):
    customer.shipping_address = Address(
        street="789 Pine St",
        city="Oakland",
        state="CA",
        postal_code="94607",
        country="US",
    )


# --8<-- [end:replace]

domain.init(traverse=False)
