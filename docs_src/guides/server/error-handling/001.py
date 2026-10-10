from protean import Domain, current_domain, handle
from protean.fields import Identifier, Integer, String

domain = Domain(name="Shop")

# --8<-- [start:model]
import logging

logger = logging.getLogger(__name__)


class ExternalServiceUnavailable(Exception):
    """The warehouse API did not answer."""


@domain.aggregate
class Order:
    sku: String(max_length=20, required=True)
    quantity: Integer(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    sku: String(max_length=20, required=True)
    quantity: Integer(required=True)


def reserve_stock(event):
    """Call the warehouse API."""
    if not warehouse.online:
        raise ExternalServiceUnavailable("warehouse API timed out")
    if event.quantity <= 0:
        raise ValueError(f"cannot reserve {event.quantity} of {event.sku}")
    warehouse.reserved.append(event.sku)


def alert_ops_team(failure, message):
    """Page the operations team."""
    alerts.append((failure, message))


# --8<-- [end:model]


class Warehouse:
    def __init__(self) -> None:
        self.online = True
        self.reserved: list[str] = []


warehouse = Warehouse()
alerts: list = []


# --8<-- [start:handler]
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event):
        reserve_stock(event)

    @classmethod
    def handle_error(cls, exc, message):
        """Called when the handler raises an exception."""
        for failure in _each(exc):
            if isinstance(failure, ExternalServiceUnavailable):
                alert_ops_team(failure, message)
        # `{exc}` on a group prints a count and drops every cause.
        logger.error(
            "OrderEventHandler failed: %s",
            "; ".join(f"{type(f).__name__}: {f}" for f in _each(exc)),
        )


def _each(exc):
    """Yield each failure, flattening an exception group."""
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _each(inner)
    else:
        yield exc


# --8<-- [end:handler]


def place_order(sku: str, quantity: int) -> Order:
    order = Order(sku=sku, quantity=quantity)
    order.raise_(OrderPlaced(order_id=order.id, sku=sku, quantity=quantity))
    current_domain.repository_for(Order).add(order)
    return order
