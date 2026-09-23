"""
All 4 Validation Layers Combined

This example demonstrates:
- Layer 1: Field constraints (required, min_value, max_length, choices)
- Layer 2: Value object invariants (@invariant.post on VO)
- Layer 3: Aggregate invariants (@invariant.pre and @invariant.post)
- Layer 4: Handler guards (authorization, context checks)
- How all layers work together in a realistic scenario

Scenario:
    An online store with:
    - Product aggregate with validated pricing (VO with invariants)
    - Inventory aggregate with stock management invariants
    - Command handler with authorization guards

Usage:
    # Layer 1: Field constraints validate on creation
    price = Price(amount=29.99, currency="USD")

    # Layer 2: VO invariant validates amount >= 0
    # Layer 3: Aggregate invariant validates stock >= reserved

    # Layer 4: Handler guard validates authorization
    domain.process(
        RestockProduct(product_id="P1", quantity=100, requested_by_role="warehouse"),
        asynchronous=False,
    )
"""

from enum import Enum

from protean import Domain, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Integer, String, ValueObject

# Domain setup
domain = Domain(__name__)


# ============================================================
# Layer 2: Value Object with Invariants
# ============================================================


@domain.value_object
class Price:
    """Price value object demonstrating Layer 1 + Layer 2.

    Layer 1: amount (required float), currency (required, 3-char string)
    Layer 2: amount must be non-negative, currency must be recognized
    """

    # Layer 1: Field constraints
    amount: Float(required=True)
    currency: String(max_length=3, min_length=3, required=True)

    # Layer 2: Cross-field / concept invariants
    @invariant.post
    def amount_must_be_non_negative(self):
        """Price amounts cannot be negative."""
        if self.amount < 0:
            raise ValidationError({"amount": ["Price amount cannot be negative"]})

    @invariant.post
    def currency_must_be_supported(self):
        """Only supported currencies are allowed."""
        supported = {"USD", "EUR", "GBP"}
        if self.currency not in supported:
            raise ValidationError(
                {"currency": [f"Unsupported currency '{self.currency}'"]}
            )


# ============================================================
# Layer 1 + Layer 3: Aggregate with Field Constraints + Invariants
# ============================================================


class ProductStatus(Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


@domain.aggregate
class Inventory:
    """Inventory aggregate demonstrating Layer 1 + Layer 3.

    Layer 1: Field constraints on all fields
    Layer 3: Business invariants on stock management
    """

    # Layer 1: Field constraints
    product_id: String(required=True, max_length=20, identifier=True)
    product_name: String(required=True, max_length=200)
    status: String(max_length=15, choices=ProductStatus, default="ACTIVE")
    current_stock: Integer(default=0, min_value=0)
    reserved_stock: Integer(default=0, min_value=0)
    price = ValueObject(Price, required=True)

    # Layer 3: Post-invariant — consistency rule
    @invariant.post
    def reserved_cannot_exceed_current_stock(self):
        """Reserved stock must not exceed current stock."""
        if self.reserved_stock > self.current_stock:
            raise ValidationError(
                {
                    "reserved_stock": [
                        f"Reserved ({self.reserved_stock}) cannot exceed "
                        f"current stock ({self.current_stock})"
                    ]
                }
            )

    # Layer 3: Pre-invariant — state guard
    @invariant.pre
    def cannot_modify_discontinued_product(self):
        """Discontinued products cannot be modified."""
        if self.status == ProductStatus.DISCONTINUED.value:
            raise ValidationError({"_entity": ["Cannot modify a discontinued product"]})

    # Business methods
    def restock(self, quantity):
        """Add stock."""
        self.current_stock = self.current_stock + quantity

    def reserve(self, quantity):
        """Reserve stock for an order."""
        available = self.current_stock - self.reserved_stock
        if quantity > available:
            raise ValidationError(
                {"quantity": [f"Cannot reserve {quantity}; only {available} available"]}
            )
        self.reserved_stock = self.reserved_stock + quantity

    def discontinue(self):
        """Mark product as discontinued."""
        self.status = ProductStatus.DISCONTINUED.value


# ============================================================
# Layer 4: Handler Guards
# ============================================================


@domain.command(part_of="Inventory")
class RestockProduct:
    """Command to restock a product."""

    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    requested_by_role: String(required=True)


RESTOCK_ALLOWED_ROLES = {"warehouse", "admin"}


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    """Handler with Layer 4 guards."""

    @handle(RestockProduct)
    def handle_restock(self, command: RestockProduct):
        """Restock a product.

        Layer 4 guards:
        - Only warehouse staff and admins can restock
        - Product must exist
        """
        # Layer 4: Authorization guard
        if command.requested_by_role not in RESTOCK_ALLOWED_ROLES:
            raise ValidationError(
                {
                    "authorization": [
                        f"Role '{command.requested_by_role}' cannot restock products"
                    ]
                }
            )

        # Layer 4: Existence guard
        repo = domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)

        # Business logic (Layer 3 invariants validate automatically)
        inventory.restock(command.quantity)
        repo.add(inventory)


if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)
    with domain.domain_context():
        # Create inventory item (Layer 1 + 2 + 3 all validate)
        inv = Inventory(
            product_id="WIDGET-01",
            product_name="Blue Widget",
            price=Price(amount=29.99, currency="USD"),
            current_stock=50,
        )
        domain.repository_for(Inventory).add(inv)
        print(f"Created: {inv.product_name}, Stock: {inv.current_stock}")

        # Restock via command (Layer 4 guard validates role)
        domain.process(
            RestockProduct(
                product_id="WIDGET-01",
                quantity=100,
                requested_by_role="warehouse",
            ),
            asynchronous=False,
        )
        updated = domain.repository_for(Inventory).get("WIDGET-01")
        print(f"Restocked: {updated.current_stock}")

        # Unauthorized restock attempt
        try:
            domain.process(
                RestockProduct(
                    product_id="WIDGET-01",
                    quantity=10,
                    requested_by_role="intern",
                ),
                asynchronous=False,
            )
        except ValidationError as e:
            print(f"Unauthorized: {e}")
