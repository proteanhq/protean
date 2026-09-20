"""
Projector handling multiple event types from the same aggregate.

This example demonstrates:
- A single projector with multiple @on decorated methods
- Handling both creation and update events for the same projection
- Each handler method responds to a different event type
- Updating existing projection records in response to state changes
- Synchronous event processing for testing

Usage:
    product = Product.create(name="Laptop", stock_quantity=50)
    domain.repository_for(Product).add(product)
    # Projector creates inventory record

    product.adjust_stock(-10)
    domain.repository_for(Product).add(product)
    # Projector updates inventory record with new stock level
"""

from protean import Domain
from protean.core.projector import on
from protean.fields import Float, Identifier, Integer, String, Text

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


@domain.event(part_of="Product")
class ProductAdded:
    """Event raised when a new product is created."""

    product_id: Identifier(required=True)
    name: String(required=True)
    description: Text(required=True)
    price: Float(required=True)
    stock_quantity: Integer(required=True)


@domain.event(part_of="Product")
class StockAdjusted:
    """Event raised when product stock is adjusted."""

    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    new_stock_quantity: Integer(required=True)


@domain.aggregate
class Product:
    """Product aggregate with stock management capabilities."""

    name: String(required=True)
    description: Text()
    price: Float(required=True)
    stock_quantity: Integer(default=0)

    @classmethod
    def create(cls, name, description, price, stock_quantity=0):
        """Factory method that creates a product and raises ProductAdded event."""
        product = cls(
            name=name,
            description=description,
            price=price,
            stock_quantity=stock_quantity,
        )
        product.raise_(
            ProductAdded(
                product_id=product.id,
                name=product.name,
                description=product.description,
                price=product.price,
                stock_quantity=product.stock_quantity,
            )
        )
        return product

    def adjust_stock(self, quantity):
        """Adjust stock level and raise StockAdjusted event."""
        self.stock_quantity += quantity
        self.raise_(
            StockAdjusted(
                product_id=self.id,
                quantity=quantity,
                new_stock_quantity=self.stock_quantity,
            )
        )


@domain.projection
class ProductInventory:
    """Projection tracking detailed product inventory information.

    Contains all product details plus current stock quantity,
    maintained by the ProductInventoryProjector.
    """

    product_id: Identifier(identifier=True, required=True)
    name: String(required=True)
    description: Text(required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)


@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    """Projector maintaining the ProductInventory projection.

    Handles both product creation and stock adjustment events
    to keep the inventory projection up to date.
    """

    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        """Create an inventory record when a new product is added."""
        repo = domain.repository_for(ProductInventory)
        inventory = ProductInventory(
            product_id=event.product_id,
            name=event.name,
            description=event.description,
            price=event.price,
            stock_quantity=event.stock_quantity,
        )
        repo.add(inventory)

    @on(StockAdjusted)
    def on_stock_adjusted(self, event: StockAdjusted):
        """Update the inventory record when stock levels change."""
        repo = domain.repository_for(ProductInventory)
        inventory = repo.get(event.product_id)
        inventory.stock_quantity = event.new_stock_quantity
        repo.add(inventory)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a product
        product = Product.create(
            name="Laptop",
            description="High-performance laptop",
            price=999.99,
            stock_quantity=50,
        )
        domain.repository_for(Product).add(product)

        # Verify initial projection
        inventory = domain.repository_for(ProductInventory).get(product.id)
        print(f"Initial stock: {inventory.stock_quantity}")
        assert inventory.stock_quantity == 50

        # Adjust stock down
        product.adjust_stock(-10)
        domain.repository_for(Product).add(product)

        # Verify updated projection
        inventory = domain.repository_for(ProductInventory).get(product.id)
        print(f"After adjustment: {inventory.stock_quantity}")
        assert inventory.stock_quantity == 40
        print("Multiple events projector working correctly!")
