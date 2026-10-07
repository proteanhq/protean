from protean import Domain
from protean.fields import HasMany, String

domain = Domain(name="Catalog")


# --8<-- [start:via]
@domain.aggregate
class Product:
    name: String(max_length=100)
    reviews = HasMany("Review", via="product_sku")


@domain.entity(part_of=Product)
class Review:
    content: String(max_length=1000)
    product_sku: String()  # Custom foreign key field


# --8<-- [end:via]
