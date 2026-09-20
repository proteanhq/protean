"""
Query field validation and immutability.

This example demonstrates:
- Required fields validated at construction time (ValidationError)
- choices / min_value constraints on query fields
- Defaults for optional fields
- Queries are immutable after construction (IncorrectUsageError on mutation)

Usage:
    query = ListProductsByCategory(category="electronics", min_rating=4)
"""

from protean import Domain
from protean.fields import Identifier, Integer, String

# Domain setup
domain = Domain()


@domain.projection
class ProductCatalog:
    """Read model for the product catalog."""

    product_id: Identifier(identifier=True)
    name: String(max_length=200)
    category: String(max_length=50)
    rating: Integer(default=0)


@domain.query(part_of="ProductCatalog")
class ListProductsByCategory:
    """List products in a category, optionally filtered by minimum rating."""

    category: String(required=True, choices=["electronics", "books", "apparel"])
    min_rating: Integer(default=0, min_value=0, max_value=5)
    page: Integer(default=1)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    query = ListProductsByCategory(category="electronics", min_rating=4)
    print("category:", query.category, "min_rating:", query.min_rating)
