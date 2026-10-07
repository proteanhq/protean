from protean import Domain
from protean.fields import Float, Identifier

domain = Domain(name="CreatingIdentitiesEarlyCarts")


# --8<-- [start:default-id]
@domain.aggregate
class Cart:
    customer_id: Identifier()
    total: Float()


with domain.domain_context():
    cart = Cart(customer_id="cust-789", total=149.99)
    print(cart.id)  # Auto-generated UUID
# --8<-- [end:default-id]
