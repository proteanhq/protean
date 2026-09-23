"""
Adding Fields with Custom Validators

This example demonstrates:
- Creating custom validator classes
- Adding fields with custom validation logic
- Combining multiple validators on a single field
- Validator configuration with parameters
- Reusing validators across fields and elements

Usage:
    python add_field_with_custom_validator.py
"""

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import String

# Domain setup
domain = Domain(__name__)


# ========================================
# Custom Validators
# ========================================


class EmailValidator:
    """Validates email address format.

    Basic email validation checking for @ symbol and domain.
    For production, consider using a more robust library.
    """

    def __init__(self):
        self.message = "Invalid email address format"

    def __call__(self, value: str):
        """Validate email format."""
        if not value:
            raise ValidationError({"_entity": [self.message]})

        # Basic checks
        if (
            "@" not in value
            or value.startswith("@")
            or value.endswith("@")
            or value.count("@") != 1
        ):
            raise ValidationError({"_entity": [self.message]})

        local, domain = value.rsplit("@", 1)

        # Check local and domain parts
        if not local or not domain or "." not in domain:
            raise ValidationError({"_entity": [self.message]})


class EmailDomainValidator:
    """Validates email belongs to specific domain.

    Example: Only allow company emails (@company.com).
    """

    def __init__(self, allowed_domain: str):
        self.allowed_domain = allowed_domain
        self.message = f"Email must be from {allowed_domain}"

    def __call__(self, value: str):
        """Check if email belongs to allowed domain."""
        if not value.endswith(f"@{self.allowed_domain}"):
            raise ValidationError({"_entity": [self.message]})


class PhoneValidator:
    """Validates US phone number format.

    Accepts various formats: (555) 123-4567, 555-123-4567, 5551234567
    """

    def __init__(self):
        self.message = "Invalid US phone number format"

    def __call__(self, value: str):
        """Validate phone number."""
        if not value:
            return  # Optional field

        # Remove common formatting
        digits = "".join(c for c in value if c.isdigit())

        # Must be exactly 10 digits
        if len(digits) != 10:
            raise ValidationError({"_entity": ["Phone must be 10 digits"]})

        # Area code cannot start with 0 or 1
        if digits[0] in ["0", "1"]:
            raise ValidationError({"_entity": ["Area code cannot start with 0 or 1"]})


class URLValidator:
    """Validates URL format.

    Checks for http:// or https:// prefix and basic structure.
    """

    def __init__(self, require_https: bool = False):
        self.require_https = require_https
        self.message = "Invalid URL format"

    def __call__(self, value: str):
        """Validate URL."""
        if not value:
            return  # Optional field

        if self.require_https:
            if not value.startswith("https://"):
                raise ValidationError({"_entity": ["URL must use HTTPS"]})
        else:
            if not (value.startswith("http://") or value.startswith("https://")):
                raise ValidationError(
                    {"_entity": ["URL must start with http:// or https://"]}
                )

        # Check for domain
        if "." not in value.split("://")[1]:
            raise ValidationError({"_entity": [self.message]})


class SlugValidator:
    """Validates slug format (lowercase, hyphens, alphanumeric).

    Slugs are URL-friendly identifiers like "my-blog-post".
    """

    def __init__(self):
        self.message = "Slug must contain only lowercase letters, numbers, and hyphens"

    def __call__(self, value: str):
        """Validate slug format."""
        if not value:
            raise ValidationError({"_entity": ["Slug is required"]})

        # Check characters
        for char in value:
            if not (char.isalnum() or char == "-"):
                raise ValidationError({"_entity": [self.message]})

        # Must not start or end with hyphen
        if value.startswith("-") or value.endswith("-"):
            raise ValidationError({"_entity": ["Slug cannot start or end with hyphen"]})

        # Must not have consecutive hyphens
        if "--" in value:
            raise ValidationError(
                {"_entity": ["Slug cannot contain consecutive hyphens"]}
            )

        # Must be lowercase
        if value != value.lower():
            raise ValidationError({"_entity": ["Slug must be lowercase"]})


# ========================================
# Domain Elements with Custom Validators
# ========================================


@domain.aggregate
class Employee:
    """Employee aggregate with validated email field.

    Demonstrates using custom validators on aggregate fields.
    """

    employee_id: String(required=True, max_length=50, identifier=True)
    name: String(required=True, max_length=100)

    # Email with format and domain validation
    email: String(
        required=True,
        max_length=254,
        validators=[
            EmailValidator(),
            EmailDomainValidator("company.com"),  # Only company emails
        ],
    )

    # Phone with format validation
    phone: String(max_length=20, validators=[PhoneValidator()])


@domain.aggregate
class BlogPost:
    """Blog post with validated slug and URL fields.

    Demonstrates multiple validators on different fields.
    """

    title: String(required=True, max_length=200)

    # Slug for URL-friendly identifier
    slug: String(
        required=True, max_length=200, unique=True, validators=[SlugValidator()]
    )

    # Content
    content: String(required=True, max_length=10000)

    # Author website (optional)
    author_website: String(
        max_length=255, validators=[URLValidator(require_https=True)]
    )


@domain.aggregate
class Customer:
    """Customer aggregate with multiple validated contact fields.

    Demonstrates combining validators with field-level constraints.
    """

    customer_id: String(required=True, max_length=50, identifier=True)
    name: String(required=True, max_length=100, min_length=2)

    # Email with validation
    email: String(required=True, max_length=254, validators=[EmailValidator()])

    # Phone with validation (optional)
    phone: String(max_length=20, validators=[PhoneValidator()])

    # Website (optional, HTTPS required)
    website: String(max_length=255, validators=[URLValidator(require_https=False)])


# ========================================
# Usage Examples
# ========================================

if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        print("=" * 60)
        print("Custom Field Validators Demo")
        print("=" * 60)
        print()

        # ========================================
        # Example 1: Valid employee
        # ========================================
        print("1. Creating valid employee:")
        try:
            employee = Employee(
                employee_id="EMP-001",
                name="John Doe",
                email="john.doe@company.com",  # Valid company email
                phone="(555) 123-4567",  # Valid phone format
            )
            print(f"   ✓ Created: {employee.name}")
            print(f"     Email: {employee.email}")
            print(f"     Phone: {employee.phone}")
        except ValidationError as e:
            print(f"   ✗ Unexpected error: {e}")
        print()

        # ========================================
        # Example 2: Invalid email domain
        # ========================================
        print("2. Testing invalid email domain:")
        try:
            invalid_employee = Employee(
                employee_id="EMP-002",
                name="Jane Smith",
                email="jane@gmail.com",  # Wrong domain!
            )
            print("   ✗ Should have rejected non-company email!")
        except ValidationError:
            print("   ✓ Correctly rejected: Email must be from company.com")
        print()

        # ========================================
        # Example 3: Invalid email format
        # ========================================
        print("3. Testing invalid email format:")
        try:
            invalid_employee = Employee(
                employee_id="EMP-003",
                name="Bob Jones",
                email="not-an-email",  # Invalid format!
            )
            print("   ✗ Should have rejected invalid email!")
        except ValidationError:
            print("   ✓ Correctly rejected: Invalid email format")
        print()

        # ========================================
        # Example 4: Valid blog post
        # ========================================
        print("4. Creating valid blog post:")
        try:
            post = BlogPost(
                title="Getting Started with Protean",
                slug="getting-started-with-protean",  # Valid slug
                content="Protean is a Python DDD framework...",
                author_website="https://example.com",  # Valid HTTPS URL
            )
            print(f"   ✓ Created: {post.title}")
            print(f"     Slug: {post.slug}")
            print(f"     Website: {post.author_website}")
        except ValidationError as e:
            print(f"   ✗ Unexpected error: {e}")
        print()

        # ========================================
        # Example 5: Invalid slug format
        # ========================================
        print("5. Testing invalid slug formats:")

        invalid_slugs = [
            ("Getting-Started", "Contains uppercase"),
            ("getting--started", "Consecutive hyphens"),
            ("-getting-started", "Starts with hyphen"),
            ("getting_started", "Contains underscore"),
        ]

        for invalid_slug, reason in invalid_slugs:
            try:
                BlogPost(
                    title="Test Post",
                    slug=invalid_slug,
                    content="Test content",
                )
                print(f"   ✗ '{invalid_slug}' - Should have been rejected!")
            except ValidationError:
                print(f"   ✓ '{invalid_slug}' - Rejected ({reason})")
        print()

        # ========================================
        # Example 6: Invalid URL
        # ========================================
        print("6. Testing URL validation:")
        try:
            post = BlogPost(
                title="Test Post",
                slug="test-post",
                content="Test content",
                author_website="http://example.com",  # HTTP not allowed!
            )
            print("   ✗ Should have rejected HTTP URL!")
        except ValidationError:
            print("   ✓ Correctly rejected: URL must use HTTPS")
        print()

        # ========================================
        # Example 7: Customer with all validations
        # ========================================
        print("7. Creating customer with validated fields:")
        try:
            customer = Customer(
                customer_id="CUST-001",
                name="Alice Johnson",
                email="alice@example.com",
                phone="555-123-4567",
                website="https://alice-portfolio.com",
            )
            print(f"   ✓ Created: {customer.name}")
            print(f"     Email: {customer.email}")
            print(f"     Phone: {customer.phone}")
            print(f"     Website: {customer.website}")
        except ValidationError as e:
            print(f"   ✗ Unexpected error: {e}")
        print()

        # ========================================
        # Example 8: Invalid phone number
        # ========================================
        print("8. Testing invalid phone numbers:")

        invalid_phones = [
            ("123", "Too short"),
            ("12345678901", "Too long"),
            ("0555123456", "Starts with 0"),
            ("1555123456", "Starts with 1"),
        ]

        for invalid_phone, reason in invalid_phones:
            try:
                Customer(
                    customer_id="CUST-999",
                    name="Test Customer",
                    email="test@example.com",
                    phone=invalid_phone,
                )
                print(f"   ✗ '{invalid_phone}' - Should have been rejected!")
            except ValidationError:
                print(f"   ✓ '{invalid_phone}' - Rejected ({reason})")

        print()
        print("=" * 60)
        print("Demo completed!")
        print("=" * 60)
