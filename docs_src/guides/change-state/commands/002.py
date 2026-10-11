from protean import Domain, current_domain, handle
from protean.fields import Identifier, List, String

domain = Domain(name="Sales")


@domain.aggregate
class Order:
    items: List(content_type=String)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(required=True)
    items: List(content_type=String, required=True)


@domain.command(part_of=Order)
class ReserveStock:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class ChargeCard:
    order_id: Identifier(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order(id=command.order_id, items=command.items)
        current_domain.repository_for(Order).add(order)
        return order.id


# --8<-- [start:modes]
def process_now(command):
    # Process synchronously (default is based on domain configuration)
    return domain.process(command, asynchronous=False)


def process_later(command):
    # Process asynchronously
    return domain.process(command, asynchronous=True)


# --8<-- [end:modes]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        print(process_now(PlaceOrder(order_id="ord-1", items=["book"])))  # ord-1
