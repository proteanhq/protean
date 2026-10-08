# --8<-- [start:handle-error]
import logging

from protean import Domain

logger = logging.getLogger(__name__)

domain = Domain(name="Payments")


@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, payload: dict) -> None:
        # Processing logic that might raise exceptions
        ...

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:
        """Custom error handling for message processing failures."""
        logger.error(f"Failed to process payment message: {exc}")
        # Perform recovery: store for retry, notify monitoring, etc.


# --8<-- [end:handle-error]
