from protean import Domain

domain = Domain(name="FieldSystemResolved")

# isort: split

# --8<-- [start:what_pydantic_sees]
from typing import Annotated, Literal

from pydantic import Field

from protean.core.entity import BaseEntity


# What Pydantic sees after metaclass resolution:
class Product(BaseEntity):
    name: Annotated[str, Field(min_length=1, max_length=50)]
    price: Annotated[float, Field(ge=0, default=0.0)]
    status: Annotated[
        Literal["active", "discontinued"], Field(default="active", max_length=255)
    ]


# --8<-- [end:what_pydantic_sees]

domain.init(traverse=False)
