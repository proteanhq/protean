from protean import Domain
from protean.fields import Identifier, String

domain = Domain()


# --8<-- [start:named-database]
@domain.projection(provider="search")
class ProductSearchIndex:
    product_id: Identifier(identifier=True)
    name: String(max_length=200)
    description: String()


# --8<-- [end:named-database]
