"""
Simple queries against a projection (read side of CQRS).

This example demonstrates:
- Defining queries with @domain.query(part_of="<Projection>")
- Queries target a projection (read model), not an aggregate
- Queries are immutable DTOs that carry read intent
- Basic field types and defaults (no associations)

Usage:
    query = GetOrderById(order_id="ORD-1")
    # answered by a query handler: domain.dispatch(query)
"""

from protean import Domain
from protean.fields import Identifier, Integer, String

# Domain setup
domain = Domain()


@domain.projection
class OrderSummary:
    """Read model for order listings and lookups."""

    order_id: Identifier(identifier=True)
    customer_name: String(max_length=100)
    status: String(max_length=20)
    total_amount: Integer(default=0)


@domain.query(part_of="OrderSummary")
class GetOrderById:
    """Fetch a single order summary by its identifier."""

    order_id: Identifier(required=True)


@domain.query(part_of="OrderSummary")
class SearchOrders:
    """Search/paginate order summaries by criteria."""

    status: String()
    customer_name: String()
    page: Integer(default=1)
    page_size: Integer(default=20)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    by_id = GetOrderById(order_id="ORD-1")
    print("lookup:", by_id.order_id)

    search = SearchOrders(status="placed")
    print("search defaults:", search.page, search.page_size)
