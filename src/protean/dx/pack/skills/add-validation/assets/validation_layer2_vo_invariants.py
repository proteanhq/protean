"""
Layer 2: Value Object Invariants

This example demonstrates:
- @invariant.post on value objects for cross-field validation
- Multiple granular invariants (one rule per invariant)
- Combining field constraints (Layer 1) with invariants (Layer 2)
- Value objects embedded in aggregates
- ValidationError with field-specific error keys

Scenario:
    A Booking aggregate uses several validated value objects:
    - DateRange: ensures end > start
    - GeoCoordinate: validates lat/lng ranges and cross-field consistency
    - Money: ensures non-negative amount and valid currency

Usage:
    booking = Booking(
        booking_id="BK-001",
        dates=DateRange(start_date="2024-06-01", end_date="2024-06-15"),
        price=Money(amount=1500.0, currency="USD"),
        location=GeoCoordinate(latitude=40.7128, longitude=-74.006),
    )
"""

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, String, ValueObject

# Domain setup
domain = Domain(__name__)

VALID_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CAD", "AUD"}


@domain.value_object
class DateRange:
    """Date range with ordering invariant.

    Layer 1: Both dates are required strings.
    Layer 2: End date must be after start date.
    """

    start_date: String(required=True, max_length=10)  # ISO format YYYY-MM-DD
    end_date: String(required=True, max_length=10)

    @invariant.post
    def end_must_be_after_start(self):
        """Business rule: date ordering."""
        if self.end_date <= self.start_date:
            raise ValidationError({"date_range": ["End date must be after start date"]})


@domain.value_object
class GeoCoordinate:
    """Geographic coordinate with range and consistency invariants.

    Layer 1: Both lat/lng are required floats.
    Layer 2: Latitude must be in [-90, 90], longitude in [-180, 180].
    """

    latitude: Float(required=True)
    longitude: Float(required=True)

    @invariant.post
    def latitude_must_be_valid(self):
        """Latitude must be between -90 and 90 degrees."""
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValidationError({"latitude": ["Latitude must be between -90 and 90"]})

    @invariant.post
    def longitude_must_be_valid(self):
        """Longitude must be between -180 and 180 degrees."""
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValidationError(
                {"longitude": ["Longitude must be between -180 and 180"]}
            )


@domain.value_object
class Money:
    """Money value object with amount and currency validation.

    Layer 1: amount required, currency required with max_length.
    Layer 2: amount must be non-negative, currency must be valid ISO code.
    """

    amount: Float(required=True)
    currency: String(max_length=3, min_length=3, required=True)

    @invariant.post
    def amount_must_be_non_negative(self):
        """Money amount cannot be negative."""
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})

    @invariant.post
    def currency_must_be_valid_iso_code(self):
        """Currency must be a recognized ISO code."""
        if self.currency not in VALID_CURRENCIES:
            raise ValidationError(
                {
                    "currency": [
                        f"Unknown currency '{self.currency}'. Must be one of: {sorted(VALID_CURRENCIES)}"
                    ]
                }
            )


@domain.aggregate
class Booking:
    """Booking aggregate using validated value objects."""

    booking_id: String(required=True, max_length=20, identifier=True)
    dates = ValueObject(DateRange, required=True)
    price = ValueObject(Money, required=True)
    location = ValueObject(GeoCoordinate)


if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)
    with domain.domain_context():
        # Valid booking
        booking = Booking(
            booking_id="BK-001",
            dates=DateRange(start_date="2024-06-01", end_date="2024-06-15"),
            price=Money(amount=1500.0, currency="USD"),
            location=GeoCoordinate(latitude=40.7128, longitude=-74.006),
        )
        print(f"Booking: {booking.booking_id}")

        # Invalid date range (end before start)
        try:
            DateRange(start_date="2024-12-31", end_date="2024-01-01")
        except ValidationError as e:
            print(f"Date invariant: {e}")

        # Invalid money (negative)
        try:
            Money(amount=-100.0, currency="USD")
        except ValidationError as e:
            print(f"Money invariant: {e}")

        # Invalid currency
        try:
            Money(amount=100.0, currency="XYZ")
        except ValidationError as e:
            print(f"Currency invariant: {e}")

        # Invalid latitude
        try:
            GeoCoordinate(latitude=91.0, longitude=0.0)
        except ValidationError as e:
            print(f"Coordinate invariant: {e}")
