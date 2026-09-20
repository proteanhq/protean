"""
Nested Value Objects - Composition

This example demonstrates:
- Value objects containing other value objects
- Deep composition for complex domain concepts
- Immutability cascading through nested structures
- Real-world example: Address with Coordinates

Usage:
    from protean_skills.value_object.assets.value_object_nested import Address
"""

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, String, ValueObject

# Domain setup (required for runnable examples)
domain = Domain(__name__)


@domain.value_object
class Coordinates:
    """
    Geographic coordinates value object.

    Represents a point on Earth using latitude and longitude.
    """

    latitude: Float(required=True, min_value=-90.0, max_value=90.0)
    longitude: Float(required=True, min_value=-180.0, max_value=180.0)


@domain.value_object
class Address:
    """
    Address value object containing nested Coordinates.

    Demonstrates composition - an address is composed of:
    - Street details
    - City/State/Postal information
    - Geographic coordinates
    """

    street: String(required=True, max_length=100)
    city: String(required=True, max_length=50)
    state: String(required=True, max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)
    coordinates = ValueObject(Coordinates)  # Nested value object

    @property
    def full_address(self) -> str:
        """Return formatted full address."""
        return f"{self.street}, {self.city}, {self.state} {self.postal_code}, {self.country}"


@domain.value_object
class ContactInfo:
    """
    Contact information containing nested Email and Phone.

    Another example of composition with multiple nested value objects.
    """

    email: String(required=True, max_length=254)
    phone: String(required=True, max_length=20)
    address = ValueObject(Address)  # Nested value object


@domain.value_object
class Money:
    """Simple money value object for demonstration."""

    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    def add(self, other: "Money") -> "Money":
        """Add two Money values, ensuring same currency."""
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot add different currencies: {self.currency} and {other.currency}"
            )
        return Money(currency=self.currency, amount=self.amount + other.amount)


@domain.value_object
class PriceWithTax:
    """
    Price with tax breakdown.

    Demonstrates multiple nested value objects of the same type.
    """

    base_price = ValueObject(Money, required=True)
    tax_amount = ValueObject(Money, required=True)

    @property
    def total(self) -> "Money":
        """Calculate total price (base + tax)."""
        return self.base_price.add(self.tax_amount)

    @invariant.post
    def same_currency(self):
        """Ensure base price and tax are in same currency."""
        if self.base_price.currency != self.tax_amount.currency:
            raise ValidationError(
                {"price": ["Base price and tax must be in same currency"]}
            )


@domain.aggregate
class Customer:
    """Customer aggregate using nested value objects."""

    name: String(required=True, max_length=100)
    email: String(required=True, max_length=254)
    shipping_address = ValueObject(Address)


@domain.aggregate
class Store:
    """Store aggregate using Address with Coordinates."""

    store_name: String(required=True, max_length=100)
    address = ValueObject(Address, required=True)


if __name__ == "__main__":
    # Create nested value objects
    coords = Coordinates(latitude=40.7128, longitude=-74.0060)
    print(f"Coordinates: {coords.latitude}, {coords.longitude}")

    # Create address with nested coordinates
    address = Address(
        street="123 Broadway",
        city="New York",
        state="NY",
        postal_code="10012",
        country="USA",
        coordinates=coords,
    )
    print(f"\nAddress: {address.full_address}")
    print(f"Location: {address.coordinates.latitude}, {address.coordinates.longitude}")

    # Can also initialize nested value objects by dict
    address2 = Address(
        street="456 Market Street",
        city="San Francisco",
        state="CA",
        postal_code="94102",
        country="USA",
        coordinates={"latitude": 37.7749, "longitude": -122.4194},
    )
    print(f"\nAddress 2: {address2.full_address}")
    print(
        f"Location 2: {address2.coordinates.latitude}, {address2.coordinates.longitude}"
    )

    # Multiple levels of nesting
    contact = ContactInfo(
        email="john@example.com", phone="+1-555-0123", address=address
    )
    print(f"\nContact: {contact.email}, {contact.phone}")
    print(f"Contact address: {contact.address.full_address}")

    # Multiple nested value objects of same type
    usd_base = Money(currency="USD", amount=100.0)
    usd_tax = Money(currency="USD", amount=8.75)

    price_breakdown = PriceWithTax(base_price=usd_base, tax_amount=usd_tax)
    print("\nPrice breakdown:")
    print(
        f"  Base: {price_breakdown.base_price.currency} {price_breakdown.base_price.amount}"
    )
    print(
        f"  Tax: {price_breakdown.tax_amount.currency} {price_breakdown.tax_amount.amount}"
    )
    print(f"  Total: {price_breakdown.total.currency} {price_breakdown.total.amount}")

    # Use in aggregates
    store = Store(
        store_name="Downtown Electronics",
        address=Address(
            street="789 Main St",
            city="Boston",
            state="MA",
            postal_code="02101",
            country="USA",
            coordinates=Coordinates(latitude=42.3601, longitude=-71.0589),
        ),
    )
    print(f"\nStore: {store.store_name}")
    print(f"Address: {store.address.full_address}")
    print(
        f"Coordinates: {store.address.coordinates.latitude}, {store.address.coordinates.longitude}"
    )

    # Immutability cascades through nesting
    print("\n--- Testing immutability ---")
    try:
        address.coordinates.latitude = 50.0  # Will raise IncorrectUsageError
    except Exception as e:
        print(f"Nested value object is also immutable: {type(e).__name__}")

    # To change nested value, replace the entire parent
    store.address = Address(
        street="999 New Street",
        city="Boston",
        state="MA",
        postal_code="02102",
        country="USA",
        coordinates=Coordinates(latitude=42.3601, longitude=-71.0589),
    )
    print(f"Updated store address: {store.address.street}")
