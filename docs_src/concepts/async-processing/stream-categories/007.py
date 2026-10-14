from protean import Domain

domain = Domain(name="ecommerce")


# --8<-- [start:descriptive]
# Good
@domain.aggregate(stream_category="customer_order")
class Order: ...


# --8<-- [end:descriptive]
DescriptiveOrder = Order


# --8<-- [start:less_clear]
# Less clear
@domain.aggregate(stream_category="ord")
class Order: ...


# --8<-- [end:less_clear]
LessClearOrder = Order
