from protean import Domain

domain = Domain(name="Catalog")


# --8<-- [start:decimal]
from protean.fields import Decimal


@domain.aggregate
class Product:
    price = Decimal(precision=19, scale=4, min_value=0)


# --8<-- [end:decimal]
