from protean import Domain
from protean.fields import HasMany, Integer, String

domain = Domain(name="Catalogue")


# --8<-- [start:aggregate]
@domain.aggregate
class Product:
    name: String(max_length=100)
    sku: String(identifier=True, max_length=20)
    reviews = HasMany("Review", via="reviewed_sku")


@domain.entity(part_of=Product)
class Review:
    content: String(max_length=1000)
    rating: Integer(min_value=1, max_value=5)
    reviewed_sku: String()  # Custom foreign key field


# --8<-- [end:aggregate]
