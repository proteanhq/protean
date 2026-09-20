"""
Projection field type validation and restrictions.

This example demonstrates:
- Projections only allow basic field types
- ValueObject, Reference, and Association fields are rejected at class definition time
- At least one identifier field is required
- Validation errors with clear messages
- How to correctly flatten complex data into basic fields

Usage:
    # These raise IncorrectUsageError:
    # - Projection with ValueObject field
    # - Projection with Reference field
    # - Projection with HasOne field
    # - Projection without identifier field
"""

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError
from protean.fields import (
    Float,
    HasOne,
    Identifier,
    Integer,
    Reference,
    String,
    ValueObject,
)

# Domain setup
domain = Domain()


# --- Supporting classes for demonstrating restrictions ---


class Email(BaseValueObject):
    """A value object for email addresses."""

    address: String(required=True)


class Role(BaseEntity):
    """An entity for user roles."""

    name: String(max_length=50)


class User(BaseAggregate):
    """An aggregate for users."""

    name: String()


# --- Correct projection: basic field types only ---


@domain.projection
class UserView:
    """Correctly defined projection with only basic field types.

    Instead of using ValueObject(Email), we flatten the email
    into a basic String field. This is the correct approach
    for projections.
    """

    user_id: Identifier(identifier=True, required=True)
    name: String(max_length=100, required=True)
    email_address: String(required=True)  # Flattened from Email value object
    role_name: String(max_length=50)  # Flattened from Role entity
    age: Integer(default=0)


@domain.projection
class OrderView:
    """Another correctly defined projection with flattened fields.

    Shows how to denormalize an order with customer and item data
    into basic field types.
    """

    order_id: Identifier(identifier=True, required=True)
    customer_name: String(max_length=100)
    customer_email: String(max_length=200)
    item_count: Integer(default=0)
    total_amount: Float(default=0.0)
    shipping_city: String(max_length=100)
    shipping_zip: String(max_length=20)


# --- Functions to demonstrate field validation errors ---


def demonstrate_value_object_allowed():
    """Show that ValueObject fields are now allowed in projections.

    Returns True if the projection is created successfully.
    """
    try:

        class ProjectionWithVO(BaseProjection):
            user_id: Identifier(identifier=True)
            email = ValueObject(Email)

        return True
    except IncorrectUsageError:
        return False  # pragma: no cover


def demonstrate_reference_restriction():
    """Show that Reference fields are not allowed in projections.

    Returns the error message if the restriction is enforced.
    """
    try:

        class BadProjection(BaseProjection):
            user_id: Identifier(identifier=True)
            role = Reference(Role)

        return None  # pragma: no cover - validation always fires
    except IncorrectUsageError as e:
        return str(e.args[0])


def demonstrate_association_restriction():
    """Show that Association (HasOne) fields are not allowed in projections.

    Returns the error message if the restriction is enforced.
    """
    try:

        class BadProjection(BaseProjection):
            user_id: Identifier(identifier=True)
            role = HasOne(Role)

        return None  # pragma: no cover - validation always fires
    except IncorrectUsageError as e:
        return str(e.args[0])


def demonstrate_missing_identifier():
    """Show that projections require at least one identifier field.

    Returns the error message if the restriction is enforced.
    """
    test_domain = Domain()

    class NoIdProjection(BaseProjection):
        first_name: String(max_length=50, required=True)

    try:
        test_domain.register(NoIdProjection)
        return None  # pragma: no cover - validation always fires
    except IncorrectUsageError as e:
        return str(e.args[0])


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    # Demonstrate field validation errors
    result = demonstrate_value_object_allowed()
    print(f"ValueObject allowed in projections: {result}")
    assert result is True

    error = demonstrate_reference_restriction()
    print(f"Reference restriction: {error}")
    assert "Projections can only contain basic field types" in error
    assert "Reference" in error

    error = demonstrate_association_restriction()
    print(f"Association restriction: {error}")
    assert "Projections can only contain basic field types" in error
    assert "HasOne" in error

    error = demonstrate_missing_identifier()
    print(f"Missing identifier: {error}")
    assert "needs to have at least one identifier" in error

    print("\nField validation working correctly!")
