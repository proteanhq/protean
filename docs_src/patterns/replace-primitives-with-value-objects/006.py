from protean import Domain
from protean.fields import Auto, String

domain = Domain(name="PrimitiveCustomer")


# --8<-- [start:customer]
@domain.aggregate
class Customer:
    customer_id: Auto(identifier=True)
    name: String(required=True)
    shipping_street: String()
    shipping_city: String()
    shipping_state: String()
    shipping_postal_code: String()
    shipping_country: String()
    billing_street: String()
    billing_city: String()
    billing_state: String()
    billing_postal_code: String()
    billing_country: String()


# --8<-- [end:customer]

domain.init(traverse=False)
