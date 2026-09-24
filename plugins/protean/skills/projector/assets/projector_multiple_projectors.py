"""
Multiple projectors maintaining different projections from the same events.

This example demonstrates:
- Two independent projectors listening to the same aggregate's events
- Each projector maintains its own projection with different data shapes
- ProductInventoryProjector tracks detailed stock quantities
- ProductCatalogProjector tracks simplified in-stock status
- Both respond to the same ProductAdded and StockAdjusted events
- Synchronous event processing for testing

Usage:
    product = Product.create(name="Laptop", description="A laptop", price=999.99, stock_quantity=50)
    domain.repository_for(Product).add(product)
    # Both projectors fire: inventory gets stock_quantity=50, catalog gets in_stock="YES"
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


# --- Projection 1: Detailed inventory ---


@domain.projection
class ProductInventory:
    """Detailed inventory projection tracking exact stock quantities.

    Optimized for inventory management views and stock reports.
    """

    product_id: Identifier(identifier=True, required=True)
    name: String(required=True)
    description: Text(required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)


# --- Projection 2: Simplified catalog ---


@domain.projection
class ProductCatalog:
    """Simplified catalog projection for product browsing.

    Optimized for storefront browsing with a simple in-stock flag
    instead of exact quantities.
    """

    product_id: Identifier(identifier=True, required=True)
    name: String(required=True)
    description: Text(required=True)
    price: Float(required=True)
    in_stock: String(choices=["YES", "NO"], default="YES")


# --- Projector 1: Inventory ---


@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    """Projector maintaining the detailed ProductInventory projection."""

    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        """Create inventory record with full stock details."""
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
        """Update inventory with exact stock quantity."""
        repo = domain.repository_for(ProductInventory)
        inventory = repo.get(event.product_id)
        inventory.stock_quantity = event.new_stock_quantity
        repo.add(inventory)


# --- Projector 2: Catalog ---


@domain.projector(projector_for=ProductCatalog, aggregates=[Product])
class ProductCatalogProjector:
    """Projector maintaining the simplified ProductCatalog projection."""

    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        """Create catalog entry with in-stock flag."""
        repo = domain.repository_for(ProductCatalog)
        entry = ProductCatalog(
            product_id=event.product_id,
            name=event.name,
            description=event.description,
            price=event.price,
            in_stock="YES" if event.stock_quantity > 0 else "NO",
        )
        repo.add(entry)

    @on(StockAdjusted)
    def on_stock_adjusted(self, event: StockAdjusted):
        """Update catalog in-stock flag based on new stock level."""
        repo = domain.repository_for(ProductCatalog)
        entry = repo.get(event.product_id)
        entry.in_stock = "YES" if event.new_stock_quantity > 0 else "NO"
        repo.add(entry)


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

        # Both projections should be populated
        inventory = domain.repository_for(ProductInventory).get(product.id)
        catalog = domain.repository_for(ProductCatalog).get(product.id)

        print(f"Inventory: {inventory.name}, Stock: {inventory.stock_quantity}")
        print(f"Catalog: {catalog.name}, In Stock: {catalog.in_stock}")
        assert inventory.stock_quantity == 50
        assert catalog.in_stock == "YES"

        # Sell all stock
        product.adjust_stock(-50)
        domain.repository_for(Product).add(product)

        inventory = domain.repository_for(ProductInventory).get(product.id)
        catalog = domain.repository_for(ProductCatalog).get(product.id)

        print("\nAfter selling all stock:")
        print(f"Inventory: Stock: {inventory.stock_quantity}")
        print(f"Catalog: In Stock: {catalog.in_stock}")
        assert inventory.stock_quantity == 0
        assert catalog.in_stock == "NO"
        print("\nMultiple projectors working correctly!")
