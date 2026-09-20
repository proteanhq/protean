"""
Basic projection definition with identifier and various field types.

This example demonstrates:
- Defining a projection with the @domain.projection decorator
- Using Identifier field with identifier=True as the primary key
- Various basic field types (String, Integer, Float, DateTime, Text)
- Default values for fields
- Projection properties: to_dict(), equality, hashing, state tracking
- Projections are denormalized, query-optimized read models

Usage:
    inventory = ProductInventory(
        product_id="PROD-001", name="Laptop",
        price=999.99, stock_quantity=50,
    )
    # Projection is a simple data container for the read side
"""

from protean import Domain
from protean.fields import DateTime, Float, Identifier, Integer, String, Text

# Domain setup
domain = Domain()


@domain.projection
class ProductInventory:
    """Read-optimized projection for product inventory data.

    This projection provides a query-friendly view of product
    stock levels. It is populated by a projector (see projector)
    in response to domain events from the Product aggregate.

    Projections only support basic field types - no References,
    Associations, or ValueObjects.
    """

    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=100, required=True)
    description: Text()
    price: Float(required=True)
    stock_quantity: Integer(default=0)
    last_updated: DateTime()


@domain.projection
class UserProfile:
    """Simple user profile projection.

    Demonstrates a projection with String-based fields
    and default values.
    """

    user_id: Identifier(identifier=True, required=True)
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50)
    email: String(required=True)
    age: Integer(default=0)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a projection instance
        inventory = ProductInventory(
            product_id="PROD-001",
            name="Laptop",
            description="High-performance laptop",
            price=999.99,
            stock_quantity=50,
        )

        # Projection properties
        print(f"Product: {inventory.name}")
        print(f"ID: {inventory.product_id}")
        print(f"Dict: {inventory.to_dict()}")
        print(f"State is new: {inventory.state_.is_new}")

        # Equality is based on identity
        inventory2 = ProductInventory(
            product_id="PROD-001",
            name="Different Name",
            price=0.0,
        )
        print(f"Same identity: {inventory == inventory2}")  # True

        inventory3 = ProductInventory(
            product_id="PROD-002",
            name="Laptop",
            price=999.99,
        )
        print(f"Different identity: {inventory == inventory3}")  # False
        print("Simple projection working correctly!")
