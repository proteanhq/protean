# --8<-- [start:full]
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from protean import Domain
from protean.fields import Float, String

domain = Domain(name="Catalog")


@domain.aggregate
class Product:
    # Assignment style works correctly with deferred annotations
    name = String(max_length=50, required=True)
    price = Float(min_value=0)

    # Raw Pydantic style also works
    metadata: Annotated[dict, Field(default_factory=dict)]


# --8<-- [end:full]
