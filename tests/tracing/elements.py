"""Shared domain elements for tracing tests.

Defines a minimal Order aggregate with commands, events, and command handlers
to exercise correlation_id and causation_id propagation through the Protean
command-processing pipeline.
"""

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.exceptions import ObjectNotFoundError
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    customer = String(required=True)
    amount = Float(required=True)


class OrderConfirmed(BaseEvent):
    order_id = Identifier(required=True)


class OrderShipped(BaseEvent):
    order_id = Identifier(required=True)
    tracking_number = String(required=True)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
class PlaceOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    customer = String(required=True)
    amount = Float(required=True)


class ConfirmOrder(BaseCommand):
    order_id = Identifier(identifier=True)


class ShipOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    tracking_number = String(required=True)


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------
class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    customer = String(required=True)
    amount = Float(required=True)
    status = String(default="PENDING")
    tracking_number = String()

    @classmethod
    def place(cls, order_id: str, customer: str, amount: float) -> "Order":
        order = cls._create_new(order_id=order_id)
        order.raise_(OrderPlaced(order_id=order_id, customer=customer, amount=amount))
        return order

    def confirm(self) -> None:
        self.raise_(OrderConfirmed(order_id=self.order_id))

    def ship(self, tracking_number: str) -> None:
        self.raise_(
            OrderShipped(order_id=self.order_id, tracking_number=tracking_number)
        )

    @apply
    def on_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.customer = event.customer
        self.amount = event.amount
        self.status = "PLACED"

    @apply
    def on_confirmed(self, event: OrderConfirmed) -> None:
        self.status = "CONFIRMED"

    @apply
    def on_shipped(self, event: OrderShipped) -> None:
        self.status = "SHIPPED"
        self.tracking_number = event.tracking_number


# ---------------------------------------------------------------------------
# Command Handler
# ---------------------------------------------------------------------------
class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def handle_place(self, command: PlaceOrder) -> str:
        order = Order.place(
            order_id=command.order_id,
            customer=command.customer,
            amount=command.amount,
        )
        current_domain.repository_for(Order).add(order)
        return order.order_id

    @handle(ConfirmOrder)
    def handle_confirm(self, command: ConfirmOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.confirm()
        repo.add(order)

    @handle(ShipOrder)
    def handle_ship(self, command: ShipOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.ship(command.tracking_number)
        repo.add(order)


# ---------------------------------------------------------------------------
# Event Handler (for causation chain testing)
#
# When an OrderPlaced event is processed, this handler automatically
# dispatches a ConfirmOrder command, creating a causal chain:
#   PlaceOrder -> OrderPlaced -> ConfirmOrder -> OrderConfirmed
# ---------------------------------------------------------------------------
class OrderPlacedAutoConfirmHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        current_domain.process(
            ConfirmOrder(order_id=event.order_id),
            asynchronous=False,
        )


# ---------------------------------------------------------------------------
# Event Handler that dispatches a new command (for causation chain testing)
#
# When an OrderConfirmed event is processed, this handler automatically
# dispatches a ShipOrder command, extending the causal chain:
#   ... -> ConfirmOrder -> OrderConfirmed -> ShipOrder -> OrderShipped
# ---------------------------------------------------------------------------
class OrderConfirmedAutoShipHandler(BaseEventHandler):
    @handle(OrderConfirmed)
    def on_order_confirmed(self, event: OrderConfirmed) -> None:
        current_domain.process(
            ShipOrder(order_id=event.order_id, tracking_number="TRACK-001"),
            asynchronous=False,
        )


# ---------------------------------------------------------------------------
# Projection and Projector (for end-to-end tracing through projections)
# ---------------------------------------------------------------------------
class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer = String()
    amount = Float()
    status = String(default="PENDING")


class OrderSummaryProjector(BaseProjector):
    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        summary = OrderSummary(
            order_id=event.order_id,
            customer=event.customer,
            amount=event.amount,
            status="PLACED",
        )
        current_domain.repository_for(OrderSummary).add(summary)

    @on(OrderConfirmed)
    def on_order_confirmed(self, event: OrderConfirmed) -> None:
        repo = current_domain.repository_for(OrderSummary)
        try:
            summary = repo.get(event.order_id)
            summary.status = "CONFIRMED"
            repo.add(summary)
        except ObjectNotFoundError:
            pass

    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped) -> None:
        repo = current_domain.repository_for(OrderSummary)
        try:
            summary = repo.get(event.order_id)
            summary.status = "SHIPPED"
            repo.add(summary)
        except ObjectNotFoundError:
            pass
