from protean import Domain, handle
from protean.fields import Identifier

domain = Domain(name="Shipping")


@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)


@domain.aggregate
class Order:
    def ship(self):
        self.raise_(OrderShipped(order_id=self.id))


# --8<-- [start:handle-error]
import logging

logger = logging.getLogger(__name__)


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderShipped)
    def reduce_stock_for_order(self, event):
        # Event handling logic that might raise exceptions
        ...

    @classmethod
    def handle_error(cls, exc: Exception, message):
        """Custom error handling for event processing failures"""
        # Log the error
        logger.error(f"Failed to process event {message.metadata.headers.type}: {exc}")

        # Perform recovery operations
        # Example: store failed events for retry, trigger compensating actions, etc.


# --8<-- [end:handle-error]
