# --8<-- [start:aggregate]
from protean import Domain

domain = Domain(name="Ordering")


@domain.aggregate(stream_category="customer_orders")
class Order: ...


# Internally becomes: "ordering::customer_orders"
# --8<-- [end:aggregate]
