"""
Command validation with field constraints.

This example demonstrates:
- Required field validation
- max_length validation on String fields
- min_value / max_value validation on numeric fields
- Default values for optional fields
- InvalidDataError when validation fails
- Validating unknown fields are rejected

Usage:
    command = RegisterUser(
        user_id="USER-001",
        email="alice@example.com",
        username="alice_smith",
        password="secureP@ss1",
    )
"""

from protean import Domain
from protean.fields import Float, Identifier, Integer, String

# Domain setup
domain = Domain()


@domain.aggregate
class User:
    """User aggregate."""

    user_id: Identifier(required=True)
    email: String(required=True)


@domain.aggregate
class Product:
    """Product aggregate."""

    product_id: Identifier(required=True)


@domain.command(part_of="User")
class RegisterUser:
    """Command to register a new user with validation constraints.

    Demonstrates:
    - required=True for mandatory fields
    - max_length for string length limits
    - Default values for optional fields
    """

    user_id: Identifier(required=True)
    email: String(required=True, max_length=250)
    username: String(required=True, max_length=50)
    password: String(required=True, max_length=255)
    age: Integer(default=21)


@domain.command(part_of="Product")
class UpdateProductPricing:
    """Command to update product pricing with numeric validation.

    Demonstrates:
    - min_value / max_value on numeric fields
    - Float field validation
    - Required vs optional fields
    """

    product_id: Identifier(required=True)
    new_price: Float(required=True, min_value=0.01)
    discount_percentage: Float(min_value=0.0, max_value=100.0)
    reason: String(max_length=500)


@domain.command(part_of="User")
class UpdateUserProfile:
    """Command to update user profile with multiple validations.

    Demonstrates combining multiple field validations.
    """

    user_id: Identifier(required=True)
    display_name: String(max_length=100)
    bio: String(max_length=1000)
    age: Integer(min_value=0, max_value=150)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Valid command
        register = RegisterUser(
            user_id="USER-001",
            email="alice@example.com",
            username="alice_smith",
            password="secureP@ss1",
        )

        print(f"Command: {register.__class__.__name__}")
        print(f"Email: {register.email}")
        print(f"Username: {register.username}")
        print(f"Age (default): {register.age}")

        # Validation: max_length exceeded
        try:
            RegisterUser(
                user_id="USER-002",
                email="bob@example.com",
                username="x" * 51,  # Exceeds max_length=50
                password="secret",
            )
        except Exception as e:
            print(f"\nmax_length validation: {type(e).__name__}")
            print(f"  Messages: {e.messages}")

        # Validation: unknown fields rejected
        try:
            RegisterUser(
                foo="bar",
                user_id="USER-003",
                email="charlie@example.com",
                username="charlie",
                password="secret",
            )
        except Exception as e:
            print(f"\nUnknown field validation: {type(e).__name__}")
            print(f"  Messages: {e.messages}")

        # Numeric validation
        valid_pricing = UpdateProductPricing(
            product_id="PROD-001",
            new_price=29.99,
            discount_percentage=15.0,
            reason="Seasonal sale",
        )

        print(f"\nCommand: {valid_pricing.__class__.__name__}")
        print(f"New Price: {valid_pricing.new_price}")
        print(f"Discount: {valid_pricing.discount_percentage}%")
