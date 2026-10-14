from protean import Domain

domain = Domain(name="StructuredLogs")

# isort: split

# --8<-- [start:structured]
# The Protean way: the event name is stable, the fields are queryable
from protean.utils.logging import get_logger

logger = get_logger(__name__)
logger.info(
    "payment_refunded", order_id="ord-123", amount=19.99, reason="customer_request"
)
# --8<-- [end:structured]

domain.init(traverse=False)
