from protean import Domain
from protean.fields import Auto, Float, String

domain = Domain(name="PrimitiveUser")


# --8<-- [start:user]
@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    name: String(required=True)
    email: String(required=True)
    phone: String()
    address_line1: String()
    address_line2: String()
    city: String()
    state: String()
    postal_code: String()
    country: String()
    balance_amount: Float(default=0.0)
    balance_currency: String(default="USD")


# --8<-- [end:user]

domain.init(traverse=False)
