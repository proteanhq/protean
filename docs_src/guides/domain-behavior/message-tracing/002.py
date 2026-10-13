from protean import Domain, current_domain, handle
from protean.fields import Identifier

domain = Domain(
    name="MyApp",
    config={"enable_outbox": True, "server": {"default_subscription_type": "stream"}},
)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder):
        order = Order(customer_id=command.customer_id)
        order.raise_(OrderPlaced(order_id=order.id))
        current_domain.repository_for(Order).add(order)
        return order.id


# --8<-- [start:outbox]
def find_outbox_records(correlation_id, message_id):
    outbox_repo = domain._get_outbox_repo("default")

    # Find all outbox messages for a business operation
    by_correlation = outbox_repo.find_by_correlation_id(correlation_id)

    # Find all messages caused by a specific message
    by_causation = outbox_repo.find_by_causation_id(message_id)

    return by_correlation, by_causation


# --8<-- [end:outbox]
