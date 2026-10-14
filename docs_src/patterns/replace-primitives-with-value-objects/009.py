from protean import Domain
from protean.fields import Auto, Float, String, ValueObject

domain = Domain(name="ValueObjectField")


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)


@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)
    country: String(max_length=2, required=True)


# --8<-- [start:order]
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address)


# --8<-- [end:order]

domain.init(traverse=False)
