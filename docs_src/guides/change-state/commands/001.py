from protean import Domain, current_domain, handle
from protean.fields import Identifier, List, String

domain = Domain(name="Sales")
domain.config["command_processing"] = "sync"


# --8<-- [start:elements]
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


# --8<-- [end:elements]


# --8<-- [start:place]
def place_order(order_id, items):
    return domain.process(
        PlaceOrder(order_id=order_id, items=items),
        idempotency_key="req-abc-123",
    )


# --8<-- [end:place]


# --8<-- [start:handler]
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # In a handler, the key is accessible via metadata
        key = command._metadata.headers.idempotency_key

        order = Order(id=command.order_id, items=command.items)
        current_domain.repository_for(Order).add(order)
        return key


# --8<-- [end:handler]


# --8<-- [start:place_once]
from protean.exceptions import DuplicateCommandError


def place_order_once(order_id, items):
    try:
        domain.process(
            PlaceOrder(order_id=order_id, items=items),
            idempotency_key="req-abc-123",
            raise_on_duplicate=True,
        )
    except DuplicateCommandError as exc:
        original_result = exc.original_result
        return original_result


# --8<-- [end:place_once]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        print(place_order("ord-42", ["book"]))  # req-abc-123
