"""
Query handler answering queries from a projection (read side of CQRS).

This example demonstrates:
- A query handler with @domain.query_handler(part_of="<Projection>")
- The @read decorator (read-side counterpart to @handle)
- Handlers RETURN values; domain.dispatch(query) hands the value back
- Reading through current_domain.view_for(Projection): .get() and .query.filter()
- No Unit of Work, no side effects

Usage:
    order = domain.dispatch(GetOrderById(order_id="ORD-1"))
    placed = domain.dispatch(ListOrdersByStatus(status="placed"))
"""

from protean import Domain, current_domain, read
from protean.fields import Identifier, Integer, String

# Domain setup
domain = Domain()


@domain.projection
class OrderSummary:
    """Read model populated by a projector (omitted here for focus)."""

    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    status: String(max_length=20)
    total_amount: Integer(default=0)


@domain.query(part_of="OrderSummary")
class GetOrderById:
    """Fetch a single order summary by id."""

    order_id: Identifier(required=True)


@domain.query(part_of="OrderSummary")
class ListOrdersByStatus:
    """List order summaries in a given status."""

    status: String(required=True)


@domain.query_handler(part_of="OrderSummary")
class OrderQueryHandler:
    """Answers order read queries from the OrderSummary projection."""

    @read(GetOrderById)
    def get_by_id(self, query: GetOrderById):
        return current_domain.view_for(OrderSummary).get(query.order_id)

    @read(ListOrdersByStatus)
    def list_by_status(self, query: ListOrdersByStatus):
        view = current_domain.view_for(OrderSummary)
        return view.query.filter(status=query.status).all().items


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Seed the read model (normally a projector does this from events)
        repo = current_domain.repository_for(OrderSummary)
        repo.add(OrderSummary(order_id="ORD-1", status="placed", total_amount=100))
        repo.add(OrderSummary(order_id="ORD-2", status="shipped", total_amount=200))
        repo.add(OrderSummary(order_id="ORD-3", status="placed", total_amount=300))

        one = domain.dispatch(GetOrderById(order_id="ORD-1"))
        print("get_by_id:", one.order_id, one.status)

        placed = domain.dispatch(ListOrdersByStatus(status="placed"))
        print("placed count:", len(placed))
