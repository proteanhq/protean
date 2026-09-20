"""
Value Object with Validation - Email

This example demonstrates:
- Custom validator for complex business rules
- Encapsulating validation logic in value object
- Using validators parameter on fields
- ValidationError on invalid data

Usage:
    from protean_skills.value_object.assets.value_object_with_validation import Email
"""

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import String, ValueObject

# Domain setup (required for runnable examples)
domain = Domain(__name__)


class EmailValidator:
    """Custom validator for email address format."""

    def __init__(self):
        self.error = "Invalid email address"

    def __call__(self, value: str):
        """Validate email address according to business rules."""
        if (
            # should contain one "@" symbol
            value.count("@") != 1
            # should not start with "@" or "."
            or value.startswith("@")
            or value.startswith(".")
            # should not end with "@" or "."
            or value.endswith("@")
            or value.endswith(".")
            # should not contain consecutive dots
            or ".." in value
            # local part should not be more than 64 characters
            or len(value.split("@")[0]) > 64
            # Each label can be up to 63 characters long
            or any(len(label) > 63 for label in value.split("@")[1].split("."))
            # Labels must start and end with alphanumeric
            or not all(
                label[0].isalnum()
                and label[-1].isalnum()
                and all(c.isalnum() or c == "-" for c in label)
                for label in value.split("@")[1].split(".")
            )
            # No spaces or unprintable characters are allowed
            or not all(c.isprintable() and not c.isspace() for c in value)
        ):
            raise ValidationError(self.error)


@domain.value_object
class Email:
    """
    Email address value object with validation.

    Encapsulates the business rules for a valid email address.
    """

    address: String(max_length=254, required=True, validators=[EmailValidator()])


@domain.aggregate
class User:
    """User aggregate with Email value object."""

    email = ValueObject(Email, required=True)
    name: String(max_length=100, required=True)
    timezone: String(max_length=50)


if __name__ == "__main__":
    # Valid email
    email1 = Email(address="john.doe@example.com")
    print(f"Valid email: {email1.address}")

    # Use in aggregate
    user = User(
        email=Email(address="jane.smith@company.io"),
        name="Jane Smith",
        timezone="America/New_York",
    )
    print(f"User: {user.name}, Email: {user.email.address}")

    # Can also initialize by attributes
    user2 = User(email_address="bob.jones@test.org", name="Bob Jones")
    print(f"User 2: {user2.name}, Email: {user2.email.address}")

    # Invalid emails - each will raise ValidationError
    invalid_emails = [
        "john.doe",  # Missing @
        "@example.com",  # Starts with @
        "john.doe@",  # Ends with @
        "john..doe@example.com",  # Consecutive dots
        "a" * 65 + "@example.com",  # Local part too long
    ]

    print("\nTesting invalid emails:")
    for invalid in invalid_emails:
        try:
            Email(address=invalid)
            print(f"  '{invalid}' - Should have failed!")
        except ValidationError as e:
            print(f"  '{invalid}' - Correctly rejected: {e}")
