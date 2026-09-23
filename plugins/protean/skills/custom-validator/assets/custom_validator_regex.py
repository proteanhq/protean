"""
Custom Validators with RegexValidator

This example demonstrates:
- Using Protean's built-in RegexValidator for pattern-based validation
- Different regex patterns for common formats (product code, postal code, hex color)
- Custom error messages with RegexValidator
- Using inverse_match for deny-list patterns
- Combining RegexValidator with field-level constraints

Scenario:
    A Product aggregate uses regex-based validators for product codes,
    color codes, and postal codes.

Usage:
    product = Product(
        sku="PRD-1234",
        color_code="#FF5733",
        warehouse_postal_code="10001",
    )
"""

from protean import Domain
from protean.fields import String, ValueObject
from protean.fields.validators import RegexValidator

# Domain setup
domain = Domain(__name__)


# RegexValidator instances - reusable across elements
sku_validator = RegexValidator(
    regex=r"^[A-Z]{3}-\d{4}$",
    message="SKU must be in format XXX-9999 (3 uppercase letters, dash, 4 digits)",
)

hex_color_validator = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="Color must be a valid hex code (e.g., #FF5733)",
)

us_postal_code_validator = RegexValidator(
    regex=r"^\d{5}(-\d{4})?$",
    message="Postal code must be 5 digits or 5+4 format (e.g., 10001 or 10001-1234)",
)

# inverse_match example: reject values containing profanity placeholder
no_profanity_validator = RegexValidator(
    regex=r"(badword|offensive)",
    message="Content contains prohibited words",
    inverse_match=True,  # Fails when pattern DOES match
)


@domain.value_object
class PostalCode:
    """US postal code value object."""

    code: String(required=True, max_length=10, validators=[us_postal_code_validator])


@domain.aggregate
class Product:
    """Product aggregate with regex-validated fields."""

    sku: String(
        required=True,
        max_length=8,
        identifier=True,
        validators=[sku_validator],
    )
    name: String(required=True, max_length=200, validators=[no_profanity_validator])
    color_code: String(max_length=7, validators=[hex_color_validator])
    warehouse_postal_code = ValueObject(PostalCode)


if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)
    with domain.domain_context():
        # Valid product
        product = Product(
            sku="PRD-1234",
            name="Blue Widget",
            color_code="#FF5733",
            warehouse_postal_code=PostalCode(code="10001"),
        )
        print(f"Product: {product.sku} - {product.name}")

        # Invalid SKU format
        try:
            Product(sku="invalid", name="Test")
        except Exception as e:
            print(f"Bad SKU: {e}")

        # Invalid hex color
        try:
            Product(sku="ABC-1234", name="Test", color_code="red")
        except Exception as e:
            print(f"Bad color: {e}")

        # Profanity check (inverse match)
        try:
            Product(sku="ABC-1234", name="This is a badword product")
        except Exception as e:
            print(f"Profanity rejected: {e}")
