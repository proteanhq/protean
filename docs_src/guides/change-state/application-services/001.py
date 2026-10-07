from protean import Domain, current_domain, use_case
from protean.fields import Identifier, List, String

domain = Domain(name="Ordering")


# --8<-- [start:service]
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items: List(content_type=String)

    @classmethod
    def create(cls, customer_id: str, items: list) -> "Order":
        return cls(customer_id=customer_id, items=items)


@domain.application_service(part_of=Order)
class OrderApplicationServices:
    @use_case
    def place_order(self, customer_id: str, items: list) -> Identifier:
        # Everything inside here runs within a UnitOfWork
        order = Order.create(customer_id=customer_id, items=items)
        current_domain.repository_for(Order).add(order)
        return order.id


# --8<-- [end:service]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        order_id = OrderApplicationServices().place_order("cust-1", ["book"])
        print(current_domain.repository_for(Order).get(order_id).items)
