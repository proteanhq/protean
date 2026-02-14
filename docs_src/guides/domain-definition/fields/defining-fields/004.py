from typing import Annotated

from pydantic import Field

from protean import Domain
from protean.fields import String, Float, Boolean

domain = Domain()


@domain.aggregate
class Product:
    # Annotation style (recommended)
    name: String(max_length=50, required=True)
    sku: String(max_length=20, unique=True)

    # Assignment style
    price = Float(min_value=0)
    in_stock = Boolean(default=True)

    # Raw Pydantic
    metadata: Annotated[dict, Field(default_factory=dict)]
