"""
Command inheritance with abstract base commands.

This example demonstrates:
- Abstract base commands that other commands extend
- Inheriting fields from parent commands
- Using @domain.command(abstract=True) decorator
- Using BaseCommand class directly for inheritance
- Concrete commands adding their own fields on top of inherited ones

Usage:
    command = CreateProduct(
        entity_id="PROD-001",
        name="Widget",
        price=9.99,
        category="electronics"
    )
    # entity_id is inherited from AbstractEntityCommand
"""

from protean import Domain
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Product:
    """Product aggregate."""

    product_id: Identifier(required=True)


@domain.aggregate
class Customer:
    """Customer aggregate."""

    customer_id: Identifier(required=True)


# Abstract command using decorator
@domain.command(abstract=True)
class AbstractEntityCommand:
    """Abstract base command for entity operations.

    This abstract command defines common fields that all
    entity-related commands should have. Abstract commands
    do not require part_of since they are never instantiated directly.
    """

    entity_id: Identifier(required=True)
    reason: String(max_length=500)


# Concrete commands inheriting from abstract
@domain.command(part_of="Product")
class CreateProduct(AbstractEntityCommand):
    """Command to create a new product, inheriting from AbstractEntityCommand.

    Inherits: entity_id, reason
    Adds: name, price, category
    """

    name: String(required=True, max_length=200)
    price: Float(required=True)
    category: String(max_length=100)


@domain.command(part_of="Product")
class UpdateProduct(AbstractEntityCommand):
    """Command to update a product, inheriting from AbstractEntityCommand.

    Inherits: entity_id, reason
    Adds: name, price
    """

    name: String(max_length=200)
    price: Float()


# Multi-level abstract hierarchy
@domain.command(abstract=True)
class AbstractAuditedCommand:
    """Abstract base with audit fields."""

    performed_by: String(required=True, max_length=100)


@domain.command(abstract=True)
class AbstractCustomerCommand(AbstractAuditedCommand):
    """Abstract base for customer commands, extending audited command.

    Inherits: performed_by
    Adds: customer_id
    """

    customer_id: Identifier(required=True)


@domain.command(part_of="Customer")
class DeactivateCustomer(AbstractCustomerCommand):
    """Command to deactivate a customer.

    Inherits: performed_by, customer_id
    Adds: deactivation_reason
    """

    deactivation_reason: String(required=True, max_length=500)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create product command with inherited fields
        create = CreateProduct(
            entity_id="PROD-001",
            name="Wireless Mouse",
            price=29.99,
            category="electronics",
            reason="New product launch",
        )

        print(f"Command: {create.__class__.__name__}")
        print(f"Entity ID (inherited): {create.entity_id}")
        print(f"Reason (inherited): {create.reason}")
        print(f"Name (own): {create.name}")
        print(f"Price (own): {create.price}")
        print(f"Category (own): {create.category}")

        # Update product command with inherited fields
        update = UpdateProduct(
            entity_id="PROD-001",
            name="Wireless Mouse Pro",
            price=39.99,
            reason="Product upgrade",
        )

        print(f"\nCommand: {update.__class__.__name__}")
        print(f"Entity ID (inherited): {update.entity_id}")
        print(f"Name: {update.name}")

        # Multi-level inheritance
        deactivate = DeactivateCustomer(
            performed_by="admin@example.com",
            customer_id="CUST-999",
            deactivation_reason="Account inactive for 2 years",
        )

        print(f"\nCommand: {deactivate.__class__.__name__}")
        print(
            f"Performed By (inherited from AbstractAuditedCommand): {deactivate.performed_by}"
        )
        print(
            f"Customer ID (inherited from AbstractCustomerCommand): {deactivate.customer_id}"
        )
        print(f"Deactivation Reason (own): {deactivate.deactivation_reason}")
