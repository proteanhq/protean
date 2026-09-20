"""
Application service demonstrating return value patterns.

This example demonstrates:
- Returning a new entity ID from a create use case
- Returning None for mutative operations
- Returning an aggregate for query use cases
- Synchronous execution guarantees (caller always receives result)

Usage:
    svc = ProductApplicationServices()
    product_id = svc.create_product(name="Widget", sku="WDG-001", price=29.99)
    svc.update_price(product_id=product_id, new_price=34.99)
    product = svc.get_product(product_id=product_id)
"""

from protean import Domain, current_domain, use_case
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Product:
    """Product aggregate for demonstrating return value patterns."""

    name: String(required=True)
    sku: String(required=True)
    price: Float(required=True)
    status: String(choices=["DRAFT", "ACTIVE", "DISCONTINUED"], default="DRAFT")

    def update_price(self, new_price: float):
        """Update the product price."""
        self.price = new_price

    def activate(self):
        """Mark the product as active."""
        self.status = "ACTIVE"

    def discontinue(self):
        """Mark the product as discontinued."""
        self.status = "DISCONTINUED"


@domain.application_service(part_of=Product)
class ProductApplicationServices:
    """Application service demonstrating various return value patterns.

    Application services always execute synchronously, so the caller
    always receives the return value immediately.
    """

    @use_case
    def create_product(self, name: str, sku: str, price: float) -> Identifier:
        """Create a new product and return its ID.

        Returns:
            Identifier: The new product's ID.
        """
        product = Product(name=name, sku=sku, price=price)
        current_domain.repository_for(Product).add(product)
        return product.id

    @use_case
    def update_price(self, product_id: Identifier, new_price: float) -> None:
        """Update a product's price.

        Returns:
            None: No return value for simple mutations.
        """
        product = current_domain.repository_for(Product).get(product_id)
        product.update_price(new_price)
        current_domain.repository_for(Product).add(product)

    @use_case
    def activate_product(self, product_id: Identifier) -> str:
        """Activate a product and return its new status.

        Returns:
            str: The product's updated status.
        """
        product = current_domain.repository_for(Product).get(product_id)
        product.activate()
        current_domain.repository_for(Product).add(product)
        return product.status

    @use_case
    def get_product(self, product_id: Identifier) -> Product:
        """Retrieve a product by ID.

        Returns:
            Product: The loaded aggregate.
        """
        return current_domain.repository_for(Product).get(product_id)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        svc = ProductApplicationServices()

        # Create — returns ID
        product_id = svc.create_product(name="Widget", sku="WDG-001", price=29.99)
        print(f"Created product ID: {product_id}")

        # Update price — returns None
        result = svc.update_price(product_id=product_id, new_price=34.99)
        print(f"Update result: {result}")

        # Activate — returns status string
        status = svc.activate_product(product_id=product_id)
        print(f"Product status: {status}")

        # Get — returns aggregate
        product = svc.get_product(product_id=product_id)
        print(f"Product: {product.name}, ${product.price}, {product.status}")
