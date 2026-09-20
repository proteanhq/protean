"""
Customer aggregate with primitive address fields (before extraction).

Demonstrates a common multi-field group that should be an Address value object.
The same field group appears on both Customer (billing) and Order (shipping),
showing cross-aggregate repetition — the strongest VO extraction signal.
"""

from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Customer:
    name = String(required=True, max_length=100)
    email = String(required=True, max_length=255)
    billing_street = String(max_length=200)
    billing_city = String(max_length=100)
    billing_state = String(max_length=50)
    billing_zip_code = String(max_length=20)
    billing_country = String(max_length=100, default="US")


@domain.aggregate
class ShippingOrder:
    customer_id = String(required=True)
    shipping_street = String(max_length=200)
    shipping_city = String(max_length=100)
    shipping_state = String(max_length=50)
    shipping_zip_code = String(max_length=20)
    shipping_country = String(max_length=100, default="US")
    status = String(default="PENDING")


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        customer = Customer(
            name="Jane Doe",
            email="jane@example.com",
            billing_street="123 Main St",
            billing_city="Springfield",
            billing_state="IL",
            billing_zip_code="62701",
        )
        print(f"Customer: {customer.name}")
        print(
            f"Address: {customer.billing_street}, {customer.billing_city}, "
            f"{customer.billing_state} {customer.billing_zip_code}"
        )
