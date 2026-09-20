"""
Event-sourced aggregate with fact events and mixed domain patterns.

This example demonstrates:
- Enabling fact events with `fact_events=True`
- Auto-generated fact events capturing complete aggregate state
- Delta events vs fact events distinction
- Mixing ES and standard aggregates in the same domain
- When to choose fact events (migration, external consumers)

Domain: Product catalog
    - Product is event-sourced with fact events (needs audit trail + external sync)
    - Category is a standard aggregate (simple CRUD, no audit needed)
    - Both coexist in the same domain

Usage:
    from es_aggregate_fact_events import Product, Category, domain

    domain.init(traverse=False)
    with domain.domain_context():
        product = Product.create(
            product_id="PROD-001", name="Widget", price=29.99, category_id="CAT-001"
        )
"""

from protean import Domain
from protean.core.aggregate import apply
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


# --- Standard aggregate (NOT event-sourced) ---


@domain.aggregate
class Category:
    """Standard aggregate — stored as state, not events.

    Simple CRUD entity that doesn't need audit trails or
    temporal queries. Demonstrates mixing patterns in one domain.
    """

    category_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    description: String(max_length=500)


# --- ES Events ---


@domain.event(part_of="Product")
class ProductCreated:
    """Delta event: captures the creation action."""

    product_id: Identifier(required=True)
    name: String(required=True)
    price: Float(required=True)
    category_id: Identifier()


@domain.event(part_of="Product")
class ProductPriceChanged:
    """Delta event: captures only the price change."""

    product_id: Identifier(required=True)
    old_price: Float(required=True)
    new_price: Float(required=True)


@domain.event(part_of="Product")
class ProductDiscontinued:
    """Delta event: captures the discontinuation action."""

    product_id: Identifier(required=True)
    reason: String()


# --- Event-sourced aggregate with fact events ---


@domain.aggregate(is_event_sourced=True, fact_events=True)
class Product:
    """Event-sourced product with automatic fact events.

    With `fact_events=True`, Protean auto-generates a ProductFactEvent
    after each persist, containing the complete current state.

    Delta events capture individual changes (ProductPriceChanged).
    Fact events capture the full snapshot (ProductFactEvent).
    External systems can subscribe to fact events instead of
    replaying individual deltas.
    """

    product_id: Identifier(identifier=True)
    name: String(required=True, max_length=200)
    price: Float(required=True, min_value=0.01)
    category_id: Identifier()
    status: String(max_length=20, default="ACTIVE")

    # --- Factory classmethod ---

    @classmethod
    def create(cls, product_id, name, price, category_id=None):
        """Create a new product in the catalog."""
        if price <= 0:
            raise ValueError("Price must be positive")
        product = cls(
            product_id=product_id, name=name, price=price, category_id=category_id
        )
        product.raise_(
            ProductCreated(
                product_id=product_id,
                name=name,
                price=price,
                category_id=category_id,
            )
        )
        return product

    # --- Business methods (validate then raise; @apply handles state) ---

    def change_price(self, new_price):
        """Change the product's price."""
        if new_price <= 0:
            raise ValueError("Price must be positive")
        if self.status != "ACTIVE":
            raise ValueError("Cannot change price of discontinued product")
        old_price = self.price
        self.raise_(
            ProductPriceChanged(
                product_id=self.product_id,
                old_price=old_price,
                new_price=new_price,
            )
        )

    def discontinue(self, reason=""):
        """Discontinue the product."""
        if self.status == "DISCONTINUED":
            raise ValueError("Product is already discontinued")
        self.raise_(ProductDiscontinued(product_id=self.product_id, reason=reason))

    # --- @apply methods (for replaying events during state reconstruction) ---

    @apply
    def product_created(self, event: ProductCreated):
        self.product_id = event.product_id
        self.name = event.name
        self.price = event.price
        self.category_id = event.category_id
        self.status = "ACTIVE"

    @apply
    def price_changed(self, event: ProductPriceChanged):
        self.price = event.new_price

    @apply
    def discontinued(self, event: ProductDiscontinued):
        self.status = "DISCONTINUED"


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        # Standard aggregate — simple CRUD
        category = Category(
            category_id="CAT-001",
            name="Electronics",
            description="Electronic devices and accessories",
        )
        print(f"Category (standard): {category.name}")

        # Event-sourced aggregate with fact events
        product = Product.create(
            product_id="PROD-001",
            name="Wireless Mouse",
            price=29.99,
            category_id="CAT-001",
        )
        print(f"\nProduct (ES+facts): {product.name}, ${product.price:.2f}")
        print(f"Delta events: {len(product._events)}")

        # Change price
        product.change_price(24.99)
        print(f"After price change: ${product.price:.2f}")
        print(f"Delta events: {len(product._events)}")

        # Discontinue
        product.discontinue(reason="Replaced by v2")
        print(f"After discontinue: status={product.status}")
        print(f"Total delta events: {len(product._events)}")
