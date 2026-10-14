from protean import Domain
from protean.fields import Identifier

domain = Domain(name="ecommerce")


# --8<-- [start:multiple_handlers]
@domain.aggregate
class Order: ...


@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)


@domain.event_handler(part_of=Order)
class OrderNotificationHandler: ...


@domain.event_handler(part_of=Order)
class OrderAnalyticsHandler: ...


@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector: ...


# --8<-- [end:multiple_handlers]
