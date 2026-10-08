# --8<-- [start:typed]
from protean import Domain, current_domain, read
from protean.core.query import BaseQuery
from protean.fields import Float, Identifier, String

domain = Domain(name="Orders")


@domain.projection
class OrderSummary:
    order_id = Identifier(identifier=True)
    status = String(max_length=20)
    total_amount = Float()


@domain.query(part_of=OrderSummary)
class GetOrderById(BaseQuery[OrderSummary]):
    order_id = Identifier(required=True)


@domain.query_handler(part_of=OrderSummary)
class OrderSummaryQueryHandler:
    @read(GetOrderById)
    def get_by_id(self, query: GetOrderById) -> OrderSummary:
        return current_domain.view_for(OrderSummary).get(query.order_id)


domain.init(traverse=False)

with domain.domain_context():
    domain.repository_for(OrderSummary).add(
        OrderSummary(order_id="order-1", status="shipped", total_amount=42.0)
    )

    order = domain.dispatch(GetOrderById(order_id="order-1"))
    # order is typed as OrderSummary, not Any
# --8<-- [end:typed]


# --8<-- [start:errors]
from protean.exceptions import IncorrectUsageError, ObjectNotFoundError

with domain.domain_context():
    try:
        result = domain.dispatch(GetOrderById(order_id="nonexistent"))
    except ObjectNotFoundError:
        # No projection record with this identifier
        ...
    except IncorrectUsageError:
        # Handle missing handler or unregistered query
        ...
# --8<-- [end:errors]
