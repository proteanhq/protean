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

    @property
    def billing_address_label(self) -> str:
        """Format the billing address by hand.

        Every aggregate that holds these primitive fields grows its own copy of
        this formatting. That duplication is the smell an Address value object
        removes.
        """
        return (
            f"{self.billing_street}, {self.billing_city}, "
            f"{self.billing_state} {self.billing_zip_code}"
        )


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
        # billing_address_label assembles the address by hand. Every aggregate
        # that holds this field group repeats that formatting, which is the
        # smell an Address value object removes. The demo does not print the
        # assembled address: it is personal data, and logging it in copied
        # example code teaches the wrong habit.
