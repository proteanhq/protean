# --8<-- [start:elements]
from protean import Domain, current_domain
from protean.core.projector import on
from protean.fields import Identifier, String

domain = Domain(name="Shop")


@domain.aggregate
class Order:
    customer_name: String(required=True)


@domain.event(part_of=Order)
class OrderCreated:
    order_id: Identifier(required=True)
    customer_name: String(required=True)


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)
    carrier: String(required=True)


@domain.event(part_of=Order)
class OrderCancelled:
    order_id: Identifier(required=True)


@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    customer_name: String()
    status: String()


@domain.projection
class ShippingReport:
    order_id: Identifier(identifier=True)
    carrier: String()


# --8<-- [end:elements]


# --8<-- [start:projectors]
@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @on(OrderCreated)
    def on_order_created(self, event: OrderCreated):
        # Create order summary
        current_domain.repository_for(OrderSummary).add(
            OrderSummary(
                order_id=event.order_id,
                customer_name=event.customer_name,
                status="CREATED",
            )
        )

    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        # Update shipping status
        self._set_status(event.order_id, "SHIPPED")

    @on(OrderCancelled)
    def on_order_cancelled(self, event: OrderCancelled):
        # Mark as cancelled
        self._set_status(event.order_id, "CANCELLED")

    def _set_status(self, order_id, status):
        repository = current_domain.repository_for(OrderSummary)
        summary = repository.get(order_id)
        summary.status = status
        repository.add(summary)


@domain.projector(projector_for=ShippingReport, aggregates=[Order])
class ShippingReportProjector:
    @on(OrderShipped)  # Same event, different projector
    def on_order_shipped(self, event: OrderShipped):
        # Update shipping metrics
        current_domain.repository_for(ShippingReport).add(
            ShippingReport(order_id=event.order_id, carrier=event.carrier)
        )


# --8<-- [end:projectors]
