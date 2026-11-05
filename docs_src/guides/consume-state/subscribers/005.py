from protean import Domain
from protean.fields import Identifier, List, String
from protean.utils.globals import current_domain

domain = Domain(name="Shipping")


@domain.aggregate
class Shipment:
    order_id: Identifier(required=True)
    items: List(content_type=String)


# --8<-- [start:subscriber]
@domain.subscriber(stream="orders", idempotent=True)
class OrderSubscriber:
    def __call__(self, payload: dict) -> None:
        current_domain.repository_for(Shipment).add(
            Shipment(order_id=payload["order_id"], items=payload["items"])
        )


# --8<-- [end:subscriber]
