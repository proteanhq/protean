# --8<-- [start:imports]
import logging
import socket

from protean import Domain, handle
from protean.core.event_handler import BaseEventHandler
from protean.core.projector import BaseProjector, on
from protean.fields import DateTime, Dict, Float, Identifier, Integer, List, String
from protean.utils.eventing import Message
from protean.utils.globals import current_domain

logger = logging.getLogger(__name__)
# --8<-- [end:imports]

domain = Domain(name="Storefront")


# --8<-- [start:model]
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    customer_name: String(required=True)
    items: List(content_type=Dict)
    total: Float(required=True)


@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)
    shipped_at: DateTime(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    customer_name: String(required=True)
    items: List(content_type=Dict)
    total: Float(required=True)
    status: String(default="new")


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


@domain.aggregate
class Shipment:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(content_type=Dict)
    status: String(default="pending")


# --8<-- [end:model]


# --8<-- [start:classifiers]
TRANSIENT_EXCEPTION_TYPES = (
    ConnectionError,
    TimeoutError,
    socket.timeout,
    OSError,
)

TRANSIENT_PATTERNS = (
    "deadlock",
    "lock timeout",
    "connection reset",
    "too many connections",
)

DATA_ERROR_TYPES = (
    KeyError,
    TypeError,
    ValueError,
)

DATA_ERROR_PATTERNS = (
    "missing required field",
    "invalid type",
    "schema",
    "deserialization",
)


def _is_transient(exc: Exception) -> bool:
    """Determine if an exception is transient and likely to succeed on retry."""
    if isinstance(exc, BaseExceptionGroup):
        # Retrying re-runs every sibling that an idempotency marker does not
        # skip, so it only helps when all of them failed transiently.
        return all(_is_transient(inner) for inner in exc.exceptions)
    if isinstance(exc, TRANSIENT_EXCEPTION_TYPES):
        return True
    msg = str(exc).lower()
    return any(p in msg for p in TRANSIENT_PATTERNS)


def _is_data_error(exc: Exception) -> bool:
    """Determine if an exception is caused by bad message data."""
    if isinstance(exc, BaseExceptionGroup):
        # One member blaming the message data is enough: a retry will hit the
        # same bad payload.
        return any(_is_data_error(inner) for inner in exc.exceptions)
    if isinstance(exc, DATA_ERROR_TYPES):
        return True
    msg = str(exc).lower()
    return any(p in msg for p in DATA_ERROR_PATTERNS)


# --8<-- [end:classifiers]

# Stand-ins for the team's alerting tools. They record each alert so a test
# can see which path a failure took.
alerts = []


def _alert_data_error(handler_name, exc, message):
    alerts.append(("data", handler_name, exc))


def _alert_logic_error(handler_name, exc, message):
    alerts.append(("logic", handler_name, exc))


def _alert_stale_projection(handler_name, exc, message):
    alerts.append(("stale", handler_name, exc))


# --8<-- [start:transient]
@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class InventoryEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(
                order_id=event.order_id,
                quantity=item["quantity"],
            )
            repo.add(inventory)

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        if _is_transient(exc):
            logger.warning(
                "Transient error in %s, will retry: %s",
                cls.__name__,
                exc,
            )
            return

        if _is_data_error(exc):
            logger.error(
                "Data error in %s, message_id=%s: %s",
                cls.__name__,
                message.metadata.headers.id if message.metadata else "unknown",
                exc,
                exc_info=exc,
            )
            _alert_data_error(cls.__name__, exc, message)
            return

        # Logic error: alert immediately
        logger.critical(
            "Logic error in %s, message_id=%s: %s",
            cls.__name__,
            message.metadata.headers.id if message.metadata else "unknown",
            exc,
            exc_info=exc,
        )
        _alert_logic_error(cls.__name__, exc, message)


# --8<-- [end:transient]


# --8<-- [start:data_errors]
@domain.event_handler(part_of=Shipment, stream_category=Order.meta_.stream_category)
class ShippingEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def create_shipment(self, event: OrderPlaced):
        repo = current_domain.repository_for(Shipment)
        repo.add(
            Shipment(
                order_id=event.order_id,
                customer_id=event.customer_id,
                items=event.items,
                status="pending",
            )
        )

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        if _is_transient(exc):
            logger.warning("Transient error in %s: %s", cls.__name__, exc)
            return

        if _is_data_error(exc):
            logger.error(
                "Data error in %s -- message will move to DLQ. "
                "message_id=%s, type=%s, error=%s",
                cls.__name__,
                message.metadata.headers.id if message.metadata else "unknown",
                message.metadata.headers.type if message.metadata else "unknown",
                exc,
                exc_info=exc,
            )
            _alert_data_error(cls.__name__, exc, message)
            return

        _alert_logic_error(cls.__name__, exc, message)


# --8<-- [end:data_errors]


# --8<-- [start:logic_errors]
# --8<-- [start:problem]
@domain.projector(projector_for=OrderDashboard, aggregates=[Order])
class OrderDashboardProjector(BaseProjector):
    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderDashboard)
        repo.add(
            OrderDashboard(
                order_id=event.order_id,
                customer_name=event.customer_name,
                status="placed",
                total=event.total,
            )
        )

    @on(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderDashboard)
        dashboard = repo.get(event.order_id)
        dashboard.status = "shipped"
        dashboard.shipped_at = event.shipped_at
        repo.add(dashboard)

    # --8<-- [end:problem]

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        if _is_transient(exc):
            logger.warning(
                "Transient error in %s (projection may be stale): %s",
                cls.__name__,
                exc,
            )
            return

        # For projectors, any non-transient error means a stale read model
        logger.critical(
            "%s in %s -- projection is stale. message_id=%s, error=%s",
            "Data error" if _is_data_error(exc) else "Logic error (BUG)",
            cls.__name__,
            message.metadata.headers.id if message.metadata else "unknown",
            exc,
            exc_info=exc,
        )
        _alert_stale_projection(cls.__name__, exc, message)


# --8<-- [end:logic_errors]


# --8<-- [start:mixin]
class ErrorClassificationMixin:
    """Classifies handler exceptions into transient, data, and logic errors.

    Subclasses override ``on_transient_error``, ``on_data_error``, or
    ``on_logic_error`` to customize behavior per handler.
    """

    _extra_transient_types: tuple = ()
    _extra_data_error_types: tuple = ()

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        if cls._classify_transient(exc):
            cls.on_transient_error(exc, message)
        elif cls._classify_data_error(exc):
            cls.on_data_error(exc, message)
        else:
            cls.on_logic_error(exc, message)

    @classmethod
    def _classify_transient(cls, exc: Exception) -> bool:
        # Retrying re-runs every sibling that an idempotency marker does not
        # skip, so it only helps when all of them failed transiently.
        if isinstance(exc, BaseExceptionGroup):
            return all(cls._classify_transient(e) for e in exc.exceptions)
        types = TRANSIENT_EXCEPTION_TYPES + cls._extra_transient_types
        if isinstance(exc, types):
            return True
        msg = str(exc).lower()
        return any(p in msg for p in TRANSIENT_PATTERNS)

    @classmethod
    def _classify_data_error(cls, exc: Exception) -> bool:
        # A group means several sibling methods failed. One member blaming the
        # message data is enough, since a retry hits the same payload.
        if isinstance(exc, BaseExceptionGroup):
            return any(cls._classify_data_error(e) for e in exc.exceptions)
        types = DATA_ERROR_TYPES + cls._extra_data_error_types
        if isinstance(exc, types):
            return True
        msg = str(exc).lower()
        return any(p in msg for p in DATA_ERROR_PATTERNS)

    @classmethod
    def on_transient_error(cls, exc: Exception, message: Message) -> None:
        logger.warning("Transient error in %s: %s", cls.__name__, exc)

    @classmethod
    def on_data_error(cls, exc: Exception, message: Message) -> None:
        logger.error("Data error in %s: %s", cls.__name__, exc, exc_info=exc)

    @classmethod
    def on_logic_error(cls, exc: Exception, message: Message) -> None:
        logger.critical("Logic error in %s: %s", cls.__name__, exc, exc_info=exc)


# --8<-- [end:mixin]
