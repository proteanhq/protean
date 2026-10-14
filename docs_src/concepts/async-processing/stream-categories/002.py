from protean import Domain

domain = Domain(name="ecommerce")


# --8<-- [start:explicit]
@domain.aggregate(stream_category="customer_orders")
class Order: ...


# Stream category: "ecommerce::customer_orders"
# --8<-- [end:explicit]
