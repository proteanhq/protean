# --8<-- [start:handler]
from protean import Domain, current_domain, read
from protean.fields import Float, Identifier, Integer, String

domain = Domain(name="Orders")


# --8<-- [start:query]
@domain.projection
class OrderSummary:
    order_id = Identifier(identifier=True)
    customer_id = Identifier()
    customer_name = String(max_length=100)
    status = String(max_length=20)
    total_amount = Float()


@domain.query(part_of=OrderSummary)
class GetOrdersByCustomer:
    customer_id = Identifier(required=True)
    status = String()
    page = Integer(default=1)
    page_size = Integer(default=20)


# --8<-- [end:query]


@domain.query(part_of=OrderSummary)
class GetOrderById:
    order_id = Identifier(required=True)


@domain.query_handler(part_of=OrderSummary)
class OrderSummaryQueryHandler:
    @read(GetOrdersByCustomer)
    def get_by_customer(self, query):
        view = current_domain.view_for(OrderSummary)
        results = view.query.filter(customer_id=query.customer_id)
        if query.status:
            results = results.filter(status=query.status)
        return results.all()

    @read(GetOrderById)
    def get_by_id(self, query):
        view = current_domain.view_for(OrderSummary)
        return view.get(query.order_id)


# --8<-- [end:handler]


# --8<-- [start:dispatch]
domain.init(traverse=False)

with domain.domain_context():
    # From an API endpoint or application layer
    result = domain.dispatch(
        GetOrdersByCustomer(customer_id="cust-123", status="shipped")
    )
# --8<-- [end:dispatch]
