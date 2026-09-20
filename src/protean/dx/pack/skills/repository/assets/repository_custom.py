"""
Custom repository with domain-specific query methods.

This example demonstrates:
- Defining a custom repository with @domain.repository decorator
- Required part_of parameter associating repository with an aggregate
- Custom query methods using self._dao for database access
- Filtering with self._dao.query.filter()
- Custom repository inherits add() and get() from BaseRepository
- Domain-specific query naming (find_by_*, find_active, etc.)

Usage:
    repo = domain.repository_for(Product)
    active_products = repo.find_active()
    cheap_products = repo.find_affordable(max_price=50.0)
"""

from protean import Domain
from protean.fields import Boolean, Float, Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Product:
    """Product aggregate for an e-commerce catalog."""

    product_id: Identifier(identifier=True)
    name: String(required=True, max_length=200)
    category: String(required=True)
    price: Float(required=True)
    is_active: Boolean(default=True)

    def deactivate(self):
        """Mark the product as inactive."""
        self.is_active = False

    def update_price(self, new_price: float):
        """Update the product price."""
        if new_price < 0:
            raise ValueError("Price cannot be negative")
        self.price = new_price


@domain.repository(part_of=Product)
class ProductRepository:
    """Custom repository for Product aggregate.

    Adds domain-specific query methods beyond the standard add/get.
    The _dao property provides access to the underlying data access object
    for building filtered queries.
    """

    def find_by_category(self, category: str):
        """Find all products in a given category."""
        return self._dao.query.filter(category=category).all()

    def find_active(self):
        """Find all active products."""
        return self._dao.query.filter(is_active=True).all()

    def find_affordable(self, max_price: float):
        """Find products at or below the given price."""
        return self._dao.query.filter(price__lte=max_price).all()

    def find_by_name(self, name: str):
        """Find a product by exact name match."""
        return self._dao.find_by(name=name)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        repo = domain.repository_for(Product)

        # Add products
        repo.add(
            Product(
                product_id="PROD-001",
                name="Widget",
                category="electronics",
                price=29.99,
            )
        )
        repo.add(
            Product(
                product_id="PROD-002",
                name="Gadget",
                category="electronics",
                price=79.99,
            )
        )
        repo.add(
            Product(
                product_id="PROD-003",
                name="Book",
                category="books",
                price=14.99,
            )
        )

        # Use custom query methods
        electronics = repo.find_by_category("electronics")
        print(f"Electronics: {len(electronics)} items")

        affordable = repo.find_affordable(max_price=50.0)
        print(f"Affordable items: {len(affordable)} items")

        active = repo.find_active()
        print(f"Active items: {len(active)} items")
