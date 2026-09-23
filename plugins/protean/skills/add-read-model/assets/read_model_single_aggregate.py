"""
Single-aggregate read model: Projection + Projector for one aggregate.

This example demonstrates:
- Defining a projection with basic field types and identifier
- Defining events that carry data for the projection
- Aggregate factory method that raises events on creation
- Aggregate method that raises events on updates
- Projector that creates and updates projection records
- End-to-end flow: aggregate mutation → event → projector → projection update

Domain: An e-commerce product catalog where the ProductListing projection
provides a query-optimized view of product data for the storefront.
"""

from protean import Domain
from protean.core.projector import on
from protean.fields import Float, Identifier, Integer, String

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Product")
class ProductAdded:
    """Raised when a new product is created."""

    product_id: Identifier(required=True)
    name: String(required=True)
    price: Float(required=True)
    stock_quantity: Integer(required=True)


@domain.event(part_of="Product")
class ProductPriceChanged:
    """Raised when a product's price is updated."""

    product_id: Identifier(required=True)
    new_price: Float(required=True)


@domain.event(part_of="Product")
class ProductStockUpdated:
    """Raised when product stock changes."""

    product_id: Identifier(required=True)
    new_stock: Integer(required=True)


# --- Aggregate (write model) ---


@domain.aggregate
class Product:
    """Product aggregate - the write model for product data."""

    name: String(required=True, max_length=200)
    price: Float(required=True)
    stock_quantity: Integer(default=0)

    @classmethod
    def create(cls, name, price, stock_quantity=0):
        """Factory method: creates product and raises ProductAdded."""
        product = cls(name=name, price=price, stock_quantity=stock_quantity)
        product.raise_(
            ProductAdded(
                product_id=product.id,
                name=product.name,
                price=product.price,
                stock_quantity=product.stock_quantity,
            )
        )
        return product

    def update_price(self, new_price):
        """Update product price and raise ProductPriceChanged."""
        self.price = new_price
        self.raise_(
            ProductPriceChanged(
                product_id=self.id,
                new_price=new_price,
            )
        )

    def adjust_stock(self, new_stock):
        """Update stock quantity and raise ProductStockUpdated."""
        self.stock_quantity = new_stock
        self.raise_(
            ProductStockUpdated(
                product_id=self.id,
                new_stock=new_stock,
            )
        )


# --- Projection (read model) ---


@domain.projection
class ProductListing:
    """Query-optimized view of product data for the storefront.

    This projection flattens product data into basic fields
    for efficient querying. Populated by ProductListingProjector.
    """

    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=200, required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)


# --- Projector ---


@domain.projector(projector_for=ProductListing, aggregates=[Product])
class ProductListingProjector:
    """Maintains the ProductListing projection from Product events.

    Handles creation, price updates, and stock updates.
    """

    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        """Create a listing record when a product is added."""
        repo = domain.repository_for(ProductListing)
        listing = ProductListing(
            product_id=event.product_id,
            name=event.name,
            price=event.price,
            stock_quantity=event.stock_quantity,
        )
        repo.add(listing)

    @on(ProductPriceChanged)
    def on_price_changed(self, event: ProductPriceChanged):
        """Update the listing price when product price changes."""
        repo = domain.repository_for(ProductListing)
        listing = repo.get(event.product_id)
        listing.price = event.new_price
        repo.add(listing)

    @on(ProductStockUpdated)
    def on_stock_updated(self, event: ProductStockUpdated):
        """Update the listing stock when product stock changes."""
        repo = domain.repository_for(ProductListing)
        listing = repo.get(event.product_id)
        listing.stock_quantity = event.new_stock
        repo.add(listing)
