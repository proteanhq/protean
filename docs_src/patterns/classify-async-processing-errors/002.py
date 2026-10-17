import importlib.util
from pathlib import Path

from protean import Domain, handle
from protean.core.event_handler import BaseEventHandler
from protean.core.projector import BaseProjector, on

# --8<-- [start:subscriber_import]
from protean.core.subscriber import BaseSubscriber

# --8<-- [end:subscriber_import]
from protean.fields import DateTime, Dict, Float, Identifier, Integer, List, String
from protean.utils.eventing import Message
from protean.utils.globals import current_domain

# The mixin is the one 001.py defines. Its folder name has a hyphen, so it
# loads by file path.
_spec = importlib.util.spec_from_file_location(
    "classify_async_processing_errors_001", Path(__file__).parent / "001.py"
)
_example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_example)
ErrorClassificationMixin = _example.ErrorClassificationMixin

domain = Domain(name="StorefrontWithMixin")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_name: String(required=True)
    items: List(content_type=Dict)
    total: Float(required=True)


@domain.command(part_of="Order")
class MarkOrderPaid:
    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    customer_name: String(required=True)
    items: List(content_type=Dict)
    total: Float(required=True)
    status: String(default="new")

    def place(self):
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_id=self.customer_id,
                customer_name=self.customer_name,
                items=self.items,
                total=self.total,
            )
        )


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(MarkOrderPaid)
    def mark_paid(self, command: MarkOrderPaid):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.status = "paid"
        repo.add(order)


@domain.projection
class OrderDashboard:
    order_id: Identifier(identifier=True)
    customer_name: String()
    status: String(required=True)
    total: Float()
    shipped_at: DateTime()


@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    on_hand: Integer(default=0)
    reserved: Integer(default=0)

    def reserve(self, order_id, quantity):
        self.on_hand -= quantity
        self.reserved += quantity


class _PagerDuty:
    """Stand-in for the PagerDuty client. It records each incident."""

    def __init__(self):
        self.incidents = []

    def trigger(self, **incident):
        self.incidents.append(incident)


pagerduty = _PagerDuty()
stale_projection_alerts = []


def _alert_stale_projection(handler_name, exc, message):
    stale_projection_alerts.append((handler_name, exc))


# --8<-- [start:handler]
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class InventoryEventHandler(ErrorClassificationMixin, BaseEventHandler):
    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(order_id=event.order_id, quantity=item["quantity"])
            repo.add(inventory)

    @classmethod
    def on_logic_error(cls, exc: Exception, message: Message) -> None:
        super().on_logic_error(exc, message)
        pagerduty.trigger(
            summary=f"Logic error in {cls.__name__}: {exc}",
            severity="critical",
        )


# --8<-- [end:handler]


# --8<-- [start:projector]
class ProjectorErrorMixin(ErrorClassificationMixin):
    """Elevated alerting for projector failures -- any non-transient error
    means the read model is stale and users see wrong data."""

    @classmethod
    def on_data_error(cls, exc: Exception, message: Message) -> None:
        super().on_data_error(exc, message)
        _alert_stale_projection(cls.__name__, exc, message)

    @classmethod
    def on_logic_error(cls, exc: Exception, message: Message) -> None:
        super().on_logic_error(exc, message)
        _alert_stale_projection(cls.__name__, exc, message)


@domain.projector(projector_for=OrderDashboard, aggregates=[Order])
class OrderDashboardProjector(ProjectorErrorMixin, BaseProjector):
    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderDashboard)
        repo.add(
            OrderDashboard(
                order_id=event.order_id,
                status="placed",
                total=event.total,
            )
        )


# --8<-- [end:projector]


# --8<-- [start:subscriber]
@domain.subscriber(stream="payments::completed")
class PaymentCompletedSubscriber(ErrorClassificationMixin, BaseSubscriber):
    def __call__(self, payload: dict) -> None:
        current_domain.process(
            MarkOrderPaid(order_id=payload["order_id"], amount=payload["amount"])
        )


# --8<-- [end:subscriber]
