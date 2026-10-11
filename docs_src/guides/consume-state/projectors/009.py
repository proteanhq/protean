from protean import Domain
from protean.core.projector import on
from protean.fields import DateTime, Float, Identifier, Integer, String, Text

domain = Domain()

# Process events and commands synchronously for demonstration
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


@domain.aggregate
class Product:
    name: String(max_length=100, required=True)
    description: Text()
    price: Float(required=True)
    stock_quantity: Integer(default=0)

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
    product_id: Identifier(required=True)
    name: String(max_length=100, required=True)
    description: Text(required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)


@domain.event(part_of=Product)
class StockAdjusted:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    new_stock_quantity: Integer(required=True)


@domain.projection
class ProductInventory:
    """Projection for product inventory data optimized for querying."""

    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=100, required=True)
    description: Text(required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)
    last_updated: DateTime()


@domain.projection
class ProductCatalog:
    """Projection for product catalog data optimized for browsing."""

    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=100, required=True)
    description: Text(required=True)
    price: Float(required=True)
    in_stock: String(choices=["YES", "NO"], default="YES")


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


# --8<-- [start:unit]
import pytest


@pytest.fixture
def test_domain():
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain


def test_product_inventory_projector_on_product_added(test_domain):
    # Create test event
    event = ProductAdded(
        product_id="test-123",
        name="Test Product",
        description="A test product",
        price=99.99,
        stock_quantity=10,
    )

    # Create projector instance
    projector = ProductInventoryProjector()

    # Call the handler method
    projector.on_product_added(event)

    # Verify projection was created
    repository = test_domain.repository_for(ProductInventory)
    inventory = repository.get("test-123")

    assert inventory.name == "Test Product"
    assert inventory.stock_quantity == 10


# --8<-- [end:unit]


# --8<-- [start:integration]
def test_projector_integration(test_domain):
    # Create and persist aggregate
    product = Product.create(
        name="Integration Test Product",
        description="Testing projector integration",
        price=149.99,
        stock_quantity=25,
    )

    product_repo = test_domain.repository_for(Product)
    product_repo.add(product)  # This triggers events

    # Verify projections were updated via view_for (read-only)
    inventory_view = test_domain.view_for(ProductInventory)
    catalog_view = test_domain.view_for(ProductCatalog)

    inventory = inventory_view.get(product.id)
    catalog = catalog_view.get(product.id)

    assert inventory.name == "Integration Test Product"
    assert catalog.in_stock == "YES"


# --8<-- [end:integration]
