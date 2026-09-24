"""
Customer aggregate with Address value object (after extraction).

Changes from extract_vo_address_before.py:
1. Extracted Address value object from the 5-field group
2. Both Customer and ShippingOrder now use ValueObject(Address)
3. Added format_oneline() behavior to Address
4. Eliminated field duplication across aggregates
"""

from protean import Domain, invariant
from protean.fields import String, ValueObject

domain = Domain()


@domain.value_object
class Address:
    """Physical mailing address."""

    street = String(required=True, max_length=200)
    city = String(required=True, max_length=100)
    state = String(required=True, max_length=50)
    zip_code = String(required=True, max_length=20)
    country = String(max_length=100, default="US")

    @invariant.post
    def zip_code_must_not_be_empty(self):
        """Zip code is required for all addresses."""
        if self.zip_code is not None and len(self.zip_code.strip()) == 0:
            from protean.exceptions import ValidationError

            raise ValidationError({"zip_code": ["Zip code cannot be empty"]})

    def format_oneline(self) -> str:
        """Format as a single-line address string."""
        return (
            f"{self.street}, {self.city}, {self.state} {self.zip_code}, {self.country}"
        )


@domain.aggregate
class Customer:
    name = String(required=True, max_length=100)
    email = String(required=True, max_length=255)
    billing_address = ValueObject(Address)


@domain.aggregate
class ShippingOrder:
    customer_id = String(required=True)
    shipping_address = ValueObject(Address)
    status = String(default="PENDING")


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        address = Address(
            street="123 Main St",
            city="Springfield",
            state="IL",
            zip_code="62701",
        )
        customer = Customer(
            name="Jane Doe",
            email="jane@example.com",
            billing_address=address,
        )
        print(f"Customer: {customer.name}")
        print(f"Address: {customer.billing_address.format_oneline()}")
