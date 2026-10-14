from protean import Domain
from protean.fields import Auto, Float, String

domain = Domain(name="PrimitiveProduct")


# --8<-- [start:product]
@domain.aggregate
class Product:
    product_id: Auto(identifier=True)
    name: String(required=True)
    price_amount: Float(required=True)
    price_currency: String(max_length=3, required=True)
    cost_amount: Float(required=True)
    cost_currency: String(max_length=3, required=True)


# --8<-- [end:product]

domain.init(traverse=False)
