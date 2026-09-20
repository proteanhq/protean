"""
Basic Custom Validators - Phone and URL

This example demonstrates:
- Creating callable validator classes from scratch
- Validating phone number format (E.164-like)
- Validating URL format
- Attaching validators to fields via validators=[] parameter
- Using validators in value objects and aggregates
- ValidationError on invalid input

Scenario:
    A Contact aggregate stores phone and website as value objects,
    each with custom format validation.

Usage:
    phone = Phone(number="+1-555-123-4567")
    url = WebUrl(url="https://example.com")
    contact = Contact(name="Acme Corp", phone=phone, website=url)
"""

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import String, ValueObject

# Domain setup
domain = Domain(__name__)


class PhoneValidator:
    """Validates phone number format.

    Accepts E.164-like format: starts with +, followed by 10-15 digits.
    Allows dashes, spaces, and parentheses as separators.
    """

    def __init__(self):
        self.error = "Invalid phone number. Must start with + followed by 10-15 digits"

    def __call__(self, value):
        # Strip common separators
        cleaned = (
            value.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        )
        if not cleaned.startswith("+"):
            raise ValidationError(self.error)
        digits = cleaned[1:]
        if not digits.isdigit() or not (10 <= len(digits) <= 15):
            raise ValidationError(self.error)


class UrlValidator:
    """Validates URL format.

    Checks for valid scheme (http/https), presence of domain,
    and basic structural validity.
    """

    VALID_SCHEMES = ("http://", "https://")

    def __init__(self):
        self.error = "Invalid URL. Must start with http:// or https://"

    def __call__(self, value):
        if not any(value.startswith(scheme) for scheme in self.VALID_SCHEMES):
            raise ValidationError(self.error)
        # Extract domain part (after scheme)
        without_scheme = value.split("://", 1)[1]
        if not without_scheme or without_scheme.startswith("/"):
            raise ValidationError(self.error)
        # Domain must contain at least one dot
        domain_part = without_scheme.split("/")[0].split(":")[0]
        if "." not in domain_part:
            raise ValidationError(self.error)


@domain.value_object
class Phone:
    """Phone number value object with format validation."""

    number: String(required=True, max_length=20, validators=[PhoneValidator()])


@domain.value_object
class WebUrl:
    """URL value object with format validation."""

    url: String(required=True, max_length=2048, validators=[UrlValidator()])


@domain.aggregate
class Contact:
    """Contact aggregate using validated value objects."""

    name: String(required=True, max_length=100)
    phone = ValueObject(Phone, required=True)
    website = ValueObject(WebUrl)


if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)
    with domain.domain_context():
        # Valid phone
        phone = Phone(number="+1-555-123-4567")
        print(f"Valid phone: {phone.number}")

        # Valid URL
        url = WebUrl(url="https://example.com/about")
        print(f"Valid URL: {url.url}")

        # Contact with both
        contact = Contact(name="Acme Corp", phone=phone, website=url)
        print(f"Contact: {contact.name}, Phone: {contact.phone.number}")

        # Invalid phone
        try:
            Phone(number="555-1234")
        except ValidationError as e:
            print(f"Invalid phone rejected: {e}")

        # Invalid URL
        try:
            WebUrl(url="ftp://files.example.com")
        except ValidationError as e:
            print(f"Invalid URL rejected: {e}")
