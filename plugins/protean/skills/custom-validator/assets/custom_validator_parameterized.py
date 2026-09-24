"""
Parameterized Custom Validators

This example demonstrates:
- Creating configurable validators with constructor parameters
- Reusing the same validator class with different configurations
- Domain-specific format validators (allowed domains, Luhn check)
- Error message customization based on parameters

Scenario:
    An Organization aggregate has different email requirements for different
    contexts — corporate emails for employees, partner emails for vendors.
    A Payment aggregate uses a configurable credit card validator.

Usage:
    org = Organization(
        name="Acme Corp",
        corporate_email="hr@acme.com",
        support_email="help@acme.com",
    )
"""

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import Float, String

# Domain setup
domain = Domain(__name__)


class AllowedDomainValidator:
    """Validates that an email belongs to one of the allowed domains.

    Configurable via constructor — reuse with different domain lists.
    """

    def __init__(self, allowed_domains):
        self.allowed_domains = [d.lower() for d in allowed_domains]
        self.error = f"Email must belong to one of: {', '.join(self.allowed_domains)}"

    def __call__(self, value):
        if "@" not in value:
            raise ValidationError("Invalid email format")
        domain_part = value.split("@")[-1].lower()
        if domain_part not in self.allowed_domains:
            raise ValidationError(self.error)


class LuhnValidator:
    """Validates a number string using the Luhn algorithm.

    Configurable via expected_length for different card types.
    Common lengths: 16 (Visa/MC), 15 (Amex), 13-19 (general).
    """

    def __init__(self, expected_length=None):
        self.expected_length = expected_length
        if expected_length:
            self.error = f"Invalid card number. Must be {expected_length} digits and pass Luhn check"
        else:
            self.error = "Invalid card number. Must pass Luhn check"

    def __call__(self, value):
        # Strip spaces and dashes
        cleaned = value.replace(" ", "").replace("-", "")

        if not cleaned.isdigit():
            raise ValidationError(self.error)

        if self.expected_length and len(cleaned) != self.expected_length:
            raise ValidationError(self.error)

        # Luhn algorithm
        digits = [int(d) for d in cleaned]
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]

        checksum = sum(odd_digits)
        for d in even_digits:
            doubled = d * 2
            checksum += doubled if doubled < 10 else doubled - 9

        if checksum % 10 != 0:
            raise ValidationError(self.error)


class StringLengthRangeValidator:
    """Validates that a string value is within a specified character range.

    Unlike field-level min_length/max_length which are tied to String fields,
    this validator can be reused and provides custom error messages.
    """

    def __init__(self, min_chars=None, max_chars=None, field_label="Value"):
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.field_label = field_label

    def __call__(self, value):
        if self.min_chars is not None and len(value) < self.min_chars:
            raise ValidationError(
                f"{self.field_label} must be at least {self.min_chars} characters"
            )
        if self.max_chars is not None and len(value) > self.max_chars:
            raise ValidationError(
                f"{self.field_label} must be at most {self.max_chars} characters"
            )


# Reuse with different configurations
corporate_validator = AllowedDomainValidator(["acme.com", "acme.io"])
partner_validator = AllowedDomainValidator(["partner.org", "vendor.net"])
visa_mc_validator = LuhnValidator(expected_length=16)
any_card_validator = LuhnValidator()


@domain.aggregate
class Organization:
    """Organization with different email domain restrictions."""

    name: String(required=True, max_length=100)
    corporate_email: String(
        required=True,
        max_length=254,
        validators=[corporate_validator],
    )
    support_email: String(
        required=True,
        max_length=254,
        validators=[corporate_validator],
    )
    partner_contact_email: String(
        max_length=254,
        validators=[partner_validator],
    )


@domain.aggregate
class Payment:
    """Payment with Luhn-validated card number."""

    card_number: String(
        required=True,
        max_length=19,
        validators=[visa_mc_validator],
    )
    amount: Float(required=True)
    description: String(
        max_length=200,
        validators=[
            StringLengthRangeValidator(
                min_chars=5, max_chars=200, field_label="Description"
            )
        ],
    )


if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)
    with domain.domain_context():
        # Valid organization
        org = Organization(
            name="Acme Corp",
            corporate_email="hr@acme.com",
            support_email="support@acme.io",
        )
        print(f"Organization: {org.name}")

        # Invalid corporate email (wrong domain)
        try:
            Organization(
                name="Bad Corp",
                corporate_email="hr@gmail.com",
                support_email="support@acme.com",
            )
        except ValidationError as e:
            print(f"Corporate email rejected: {e}")

        # Valid Visa card (passes Luhn)
        payment = Payment(
            card_number="4111111111111111",
            amount=99.99,
            description="Monthly subscription",
        )
        print(f"Payment: ${payment.amount}")

        # Invalid card number (fails Luhn)
        try:
            Payment(
                card_number="4111111111111112",
                amount=50.0,
                description="Test payment",
            )
        except ValidationError as e:
            print(f"Card rejected: {e}")
