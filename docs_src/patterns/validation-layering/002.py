# --8<-- [start:product]
from protean import Domain
from protean.fields import Auto, Float, Integer, String

domain = Domain(name="ValidationLayeringFields")


@domain.aggregate
class Product:
    product_id: Auto(identifier=True)
    name: String(required=True, max_length=200)
    sku: String(required=True, max_length=20)
    price: Float(required=True, min_value=0.0)
    weight_kg: Float(min_value=0.0)
    stock_count: Integer(min_value=0, default=0)
    status: String(choices=["draft", "active", "discontinued"], default="draft")


# --8<-- [end:product]

domain.init(traverse=False)
