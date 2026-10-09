# --8<-- [start:domain]
from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier

domain = Domain(
    name="Shop",
    config={"server": {"default_subscription_type": "stream"}},
)
# --8<-- [end:domain]


# --8<-- [start:inspect]
def print_abandoned():
    with domain.domain_context():
        repo = domain._get_outbox_repo("default")
        for msg in repo.find_abandoned(limit=None):
            print(msg.id, msg.stream_name, msg.last_error)


# --8<-- [end:inspect]


@domain.aggregate
class Order:
    total: Float(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    total: Float(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)
    total: Float(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> None:
        order = Order(id=command.order_id, total=command.total)
        order.raise_(OrderPlaced(order_id=order.id, total=order.total))
        current_domain.repository_for(Order).add(order)
