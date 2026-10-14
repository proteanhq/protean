from protean import Domain

domain = Domain(name="ecommerce")


# --8<-- [start:consistent]
# Consistent: all use snake_case
stream_category = "customer_order"
stream_category = "order_item"
stream_category = "order_shipment"

# Inconsistent: mixed styles
stream_category = "customerOrder"
stream_category = "order-item"
stream_category = "OrderShipment"
# --8<-- [end:consistent]


# --8<-- [start:grouping]
@domain.aggregate(stream_category="order")
class Order: ...


@domain.aggregate(stream_category="order_item")
class OrderItem: ...


@domain.aggregate(stream_category="order_shipment")
class Shipment: ...


# --8<-- [end:grouping]


# --8<-- [start:override]
# Default would be "purchase_order"
@domain.aggregate(stream_category="order")
class PurchaseOrder: ...


# --8<-- [end:override]
