"""
Value Object with Invariants - Cross-field Validation

This example demonstrates:
- Using @invariant.post decorator for cross-field validation
- Business rules that span multiple attributes
- Validation at initialization time
- ValidationError on invariant violation

Usage:
    from protean_skills.value_object.assets.value_object_with_invariants import Balance
"""

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, String, ValueObject

# Domain setup (required for runnable examples)
domain = Domain(__name__)


@domain.value_object
class Balance:
    """
    Balance value object with cross-field validation.

    Business rule: USD balances cannot be negative.
    This is an example of an invariant - a rule that must always be true.
    """

    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    @invariant.post
    def check_balance_is_positive_if_currency_is_usd(self):
        """
        Invariant: USD balances cannot be negative.

        This method is automatically called after initialization.
        Invariants are checked every time the value object is created.
        """
        if self.amount < 0 and self.currency == "USD":
            raise ValidationError({"balance": ["Balance cannot be negative for USD"]})


@domain.value_object
class DateRange:
    """
    DateRange value object demonstrating start/end date validation.

    Business rule: End date must be after start date.
    """

    start_date: String(required=True)  # ISO date string for simplicity
    end_date: String(required=True)  # ISO date string for simplicity

    @invariant.post
    def end_date_must_be_after_start_date(self):
        """Invariant: End date must be after or equal to start date."""
        if self.end_date < self.start_date:
            raise ValidationError(
                {"date_range": ["End date must be after or equal to start date"]}
            )


@domain.value_object
class DiscountPercentage:
    """
    Discount percentage with reasonable bounds.

    Business rules:
    - Discount must be between 0 and 100 (enforced by field-level validation)
    - Maximum discount is 50% for regular customers (enforced by invariant)
    """

    # Field-level validation for data type constraints
    percentage: Float(required=True, min_value=0.0, max_value=100.0)
    customer_type: String(max_length=20, required=True)  # regular, premium

    @invariant.post
    def regular_customer_discount_limit(self):
        """Invariant: Regular customers can only get up to 50% discount."""
        if self.customer_type == "regular" and self.percentage > 50:
            raise ValidationError(
                {"discount": ["Regular customers can only receive up to 50% discount"]}
            )


@domain.aggregate
class Account:
    """Account aggregate using Balance with invariants."""

    balance = ValueObject(Balance, required=True)
    name: String(max_length=50, required=True)


if __name__ == "__main__":
    # Valid USD balance (positive)
    bal1 = Balance(currency="USD", amount=100.0)
    print(f"Valid USD balance: {bal1.currency} {bal1.amount}")

    # Valid non-USD balance (can be negative)
    bal2 = Balance(currency="EUR", amount=-50.0)
    print(f"Valid EUR balance: {bal2.currency} {bal2.amount}")

    # Invalid USD balance (negative) - will raise ValidationError
    print("\nTrying to create negative USD balance:")
    try:
        Balance(currency="USD", amount=-100.0)
        print("Should have failed!")
    except ValidationError as e:
        print(f"Invariant enforced: {e}")

    # Valid date range
    date_range1 = DateRange(start_date="2024-01-01", end_date="2024-12-31")
    print(f"\nValid date range: {date_range1.start_date} to {date_range1.end_date}")

    # Invalid date range (end before start)
    print("Trying to create invalid date range:")
    try:
        DateRange(start_date="2024-12-31", end_date="2024-01-01")
        print("Should have failed!")
    except ValidationError as e:
        print(f"Invariant enforced: {e}")

    # Valid discounts
    discount1 = DiscountPercentage(percentage=30.0, customer_type="regular")
    print(f"\nValid regular customer discount: {discount1.percentage}%")

    discount2 = DiscountPercentage(percentage=75.0, customer_type="premium")
    print(f"Valid premium customer discount: {discount2.percentage}%")

    # Invalid discount (too high for regular customer)
    print("\nTrying to create high discount for regular customer:")
    try:
        DiscountPercentage(percentage=60.0, customer_type="regular")
        print("Should have failed!")
    except ValidationError as e:
        print(f"Invariant enforced: {e}")

    # Invalid discount (out of range)
    print("\nTrying to create out-of-range discount:")
    try:
        DiscountPercentage(percentage=150.0, customer_type="premium")
        print("Should have failed!")
    except ValidationError as e:
        print(f"Invariant enforced: {e}")

    # Use in aggregate
    account = Account(
        balance=Balance(currency="USD", amount=1000.0), account_number="ACC-12345"
    )
    print(
        f"\nAccount created: {account.account_number}, Balance: {account.balance.amount}"
    )
