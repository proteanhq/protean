"""
Projector that listens to a single aggregate's events and maintains a projection.

This example demonstrates:
- Basic projector definition with @domain.projector decorator
- Association with a projection via projector_for
- Association with an aggregate via aggregates parameter
- Using @on decorator (from protean.core.projector) for event handling
- Creating projection records in response to domain events
- Synchronous event processing for testing

Usage:
    product = Product.create(name="Laptop", stock_quantity=50)
    domain.repository_for(Product).add(product)
    # ProductInventoryProjector automatically creates ProductInventory projection
"""

from protean import Domain
from protean.core.projector import on
from protean.fields import Identifier, Integer, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


@domain.event(part_of="Product")
class ProductAdded:
    """Event raised when a new product is created."""

    product_id: Identifier(required=True)
    name: String(required=True)
    stock_quantity: Integer(required=True)


@domain.aggregate
class Product:
    """Product aggregate representing the write model."""

    name: String(required=True)
    stock_quantity: Integer(default=0)

    @classmethod
    def create(cls, name, stock_quantity=0):
        """Factory method that creates a product and raises ProductAdded event."""
        product = cls(name=name, stock_quantity=stock_quantity)
        product.raise_(
            ProductAdded(
                product_id=product.id,
                name=product.name,
                stock_quantity=product.stock_quantity,
            )
        )
        return product


@domain.projection
class ProductInventory:
    """Read-optimized projection for product inventory data.

    This projection is maintained by ProductInventoryProjector
    and provides a query-friendly view of product stock levels.
    """

    product_id: Identifier(identifier=True, required=True)
    name: String(required=True)
    stock_quantity: Integer(default=0)


@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    """Projector that maintains the ProductInventory projection.

    Listens to Product aggregate events and creates/updates
    corresponding ProductInventory projection records.
    """

    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        """Create an inventory projection record when a product is added."""
        repo = domain.repository_for(ProductInventory)
        inventory = ProductInventory(
            product_id=event.product_id,
            name=event.name,
            stock_quantity=event.stock_quantity,
        )
        repo.add(inventory)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a new product (raises ProductAdded event)
        product = Product.create(name="Laptop", stock_quantity=50)
        domain.repository_for(Product).add(product)

        # Verify the projection was populated
        inventory = domain.repository_for(ProductInventory).get(product.id)
        print(f"Product: {product.name} (Stock: {product.stock_quantity})")
        print(f"Projection: {inventory.name} (Stock: {inventory.stock_quantity})")
        assert inventory.stock_quantity == 50
        print("Single-aggregate projector working correctly!")
