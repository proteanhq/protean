# --8<-- [start:elements]
from protean import Domain, current_domain
from protean.core.projector import on
from protean.fields import DateTime, Identifier, String

domain = Domain(name="Shop")


@domain.aggregate
class Order:
    customer_name: String(required=True)


@domain.event(part_of=Order)
class OrderCreated:
    order_id: Identifier(required=True)


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)


@domain.projection
class OrderStatus:
    order_id: Identifier(identifier=True)
    status: String()
    last_updated: DateTime()


# --8<-- [end:elements]


# --8<-- [start:projector]
@domain.projector(projector_for=OrderStatus, aggregates=[Order])
class OrderStatusProjector:
    @on(OrderCreated)
    def on_order_created(self, event: OrderCreated):
        repository = current_domain.repository_for(OrderStatus)

        # Use event timestamp to handle ordering
        status = OrderStatus(
            order_id=event.order_id,
            status="CREATED",
            last_updated=event._metadata.headers.time,
        )
        repository.add(status)

    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repository = current_domain.repository_for(OrderStatus)
        status = repository.get(event.order_id)

        # Only update if this event is newer
        if event._metadata.headers.time > status.last_updated:
            status.status = "SHIPPED"
            status.last_updated = event._metadata.headers.time
            repository.add(status)


# --8<-- [end:projector]
