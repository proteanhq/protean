from protean import Domain

# isort: split

# --8<-- [start:get-logger]
from protean.utils.logging import get_logger

logger = get_logger(__name__)
logger.info("order_placed", order_id="ord-123", total=99.95)
# --8<-- [end:get-logger]

# --8<-- [start:refund]
from protean.utils.logging import get_logger

logger = get_logger(__name__)
logger.info(
    "payment_refunded", order_id="ord-123", amount=19.99, reason="customer_request"
)
# --8<-- [end:refund]

# --8<-- [start:context]
from protean.utils.logging import add_context, clear_context

add_context(request_id="abc-123", tenant_id="tenant-42")
try:
    logger.info("processing")  # includes request_id and tenant_id
    logger.info("processed")
finally:
    clear_context()
# --8<-- [end:context]

domain = Domain(name="Orders")
