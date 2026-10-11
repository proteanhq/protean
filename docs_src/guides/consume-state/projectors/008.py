# --8<-- [start:elements]
from protean import Domain, current_domain
from protean.core.projector import on
from protean.fields import Identifier, String

domain = Domain(name="Shop")


@domain.aggregate
class Order:
    customer_name: String(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_name: String(required=True)


@domain.event(part_of=Order)
class OrderDelivered:
    order_id: Identifier(required=True)


@domain.projection
class ActiveOrder:
    order_id: Identifier(identifier=True)
    customer_name: String()
    status: String()


# --8<-- [end:elements]


# --8<-- [start:projector]
@domain.projector(projector_for=ActiveOrder, aggregates=[Order])
class ActiveOrderProjector:
    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repository = current_domain.repository_for(ActiveOrder)
        repository.add(
            ActiveOrder(
                order_id=event.order_id,
                customer_name=event.customer_name,
                status="placed",
            )
        )

    @on(OrderDelivered)
    def on_order_delivered(self, event: OrderDelivered):
        repository = current_domain.repository_for(ActiveOrder)
        repository.query.filter(order_id=event.order_id).delete()


# --8<-- [end:projector]
