# --8<-- [start:place_order]
from protean import Domain, handle
from protean.exceptions import ObjectNotFoundError
from protean.fields import Float, Identifier, List, String
from protean.utils.globals import current_domain

domain = Domain(name="Orders")


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    items: List(content_type=String)
    total: Float()


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)
    items: List(content_type=String)
    total: Float()


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> str:
        repo = current_domain.repository_for(Order)

        # If the order already exists, this command was already handled.
        # `repo.get` raises ObjectNotFoundError when there is no such order.
        try:
            repo.get(command.order_id)
            return command.order_id
        except ObjectNotFoundError:
            pass

        order = Order(
            order_id=command.order_id,
            items=command.items,
            total=command.total,
        )
        repo.add(order)
        return order.order_id


# --8<-- [end:place_order]
