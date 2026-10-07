from protean import Domain
from protean.fields import Float, String

domain = Domain(name="Catalog")


# --8<-- [start:product]
@domain.aggregate
class Product:
    name: String(max_length=50, required=True)  # annotation (recommended)
    price = Float(min_value=0)  # assignment


# --8<-- [end:product]
