from protean import Domain
from protean.core.projector import on
from datetime import datetime
from typing import Annotated
from pydantic import Field

domain = Domain()

# Process events and commands synchronously for demonstration
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.aggregate
class Product:
    name: Annotated[str, Field(max_length=100)]
    description: str | None = None
    price: float
    stock_quantity: int = 0

    def adjust_stock(self, quantity):
        self.stock_quantity += quantity
        self.raise_(
            StockAdjusted(
                product_id=self.id,
                quantity=quantity,
                new_stock_quantity=self.stock_quantity,
            )
        )

    @classmethod
    def create(cls, name, description, price, stock_quantity=0):
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


@domain.event(part_of=Product)
class ProductAdded:
    product_id: str
    name: Annotated[str, Field(max_length=100)]
    description: str
    price: float
    stock_quantity: int = 0


@domain.event(part_of=Product)
class StockAdjusted:
    product_id: str
    quantity: int
    new_stock_quantity: int


@domain.projection
class ProductInventory:
    """Projection for product inventory data optimized for querying."""

    product_id: str = Field(json_schema_extra={"identifier": True})
    name: Annotated[str, Field(max_length=100)]
    description: str
    price: float
    stock_quantity: int = 0
    last_updated: datetime | None = None


@domain.projection
class ProductCatalog:
    """Projection for product catalog data optimized for browsing."""

    product_id: str = Field(json_schema_extra={"identifier": True})
    name: Annotated[str, Field(max_length=100)]
    description: str
    price: float
    in_stock: str = Field(default="YES", json_schema_extra={"choices": ["YES", "NO"]})


@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    """Projector that maintains the ProductInventory projection."""

    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        """Create inventory record when a new product is added."""
        repository = domain.repository_for(ProductInventory)

        inventory = ProductInventory(
            product_id=event.product_id,
            name=event.name,
            description=event.description,
            price=event.price,
            stock_quantity=event.stock_quantity,
            last_updated=event._metadata.headers.time,
        )

        repository.add(inventory)

    @on(StockAdjusted)
    def on_stock_adjusted(self, event: StockAdjusted):
        """Update inventory when stock levels change."""
        repository = domain.repository_for(ProductInventory)
        inventory = repository.get(event.product_id)

        inventory.stock_quantity = event.new_stock_quantity
        inventory.last_updated = event._metadata.headers.time

        repository.add(inventory)


@domain.projector(projector_for=ProductCatalog, aggregates=[Product])
class ProductCatalogProjector:
    """Projector that maintains the ProductCatalog projection."""

    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        """Create catalog entry when a new product is added."""
        repository = domain.repository_for(ProductCatalog)

        catalog_entry = ProductCatalog(
            product_id=event.product_id,
            name=event.name,
            description=event.description,
            price=event.price,
            in_stock="YES" if event.stock_quantity > 0 else "NO",
        )

        repository.add(catalog_entry)

    @on(StockAdjusted)
    def on_stock_adjusted(self, event: StockAdjusted):
        """Update catalog availability when stock changes."""
        repository = domain.repository_for(ProductCatalog)
        catalog_entry = repository.get(event.product_id)

        catalog_entry.in_stock = "YES" if event.new_stock_quantity > 0 else "NO"

        repository.add(catalog_entry)


# Initialize the domain
domain.init(traverse=False)

# Demonstrate the projector workflow
if __name__ == "__main__":
    with domain.domain_context():
        # Create a new product
        product = Product.create(
            name="Laptop",
            description="High-performance laptop",
            price=999.99,
            stock_quantity=50,
        )

        # Persist the product (this will trigger ProductAdded event)
        product_repo = domain.repository_for(Product)
        product_repo.add(product)

        # Verify projections were updated
        inventory_repo = domain.repository_for(ProductInventory)
        catalog_repo = domain.repository_for(ProductCatalog)

        inventory = inventory_repo.get(product.id)
        catalog = catalog_repo.get(product.id)

        print("=== After Product Creation ===")
        print(f"Product: {product.name} (Stock: {product.stock_quantity})")
        print(
            f"Inventory Projection: {inventory.name} (Stock: {inventory.stock_quantity})"
        )
        print(f"Catalog Projection: {catalog.name} (In Stock: {catalog.in_stock})")

        # Adjust stock (this will trigger StockAdjusted event)
        product.adjust_stock(-30)  # Sell 30 units
        product_repo.add(product)

        # Verify projections were updated again
        inventory = inventory_repo.get(product.id)
        catalog = catalog_repo.get(product.id)

        print("\n=== After Stock Adjustment ===")
        print(f"Product: {product.name} (Stock: {product.stock_quantity})")
        print(
            f"Inventory Projection: {inventory.name} (Stock: {inventory.stock_quantity})"
        )
        print(f"Catalog Projection: {catalog.name} (In Stock: {catalog.in_stock})")

        # Sell all remaining stock
        product.adjust_stock(-20)  # Sell remaining 20 units
        product_repo.add(product)

        # Verify out-of-stock status
        inventory = inventory_repo.get(product.id)
        catalog = catalog_repo.get(product.id)

        print("\n=== After Selling All Stock ===")
        print(f"Product: {product.name} (Stock: {product.stock_quantity})")
        print(
            f"Inventory Projection: {inventory.name} (Stock: {inventory.stock_quantity})"
        )
        print(f"Catalog Projection: {catalog.name} (In Stock: {catalog.in_stock})")

        # Assertions for testing
        assert inventory.stock_quantity == 0
        assert catalog.in_stock == "NO"
        print("\n✅ All projections updated correctly!")
