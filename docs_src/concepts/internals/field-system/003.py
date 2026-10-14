from protean import Domain

domain = Domain(name="FieldStyles")

# isort: split

# --8<-- [start:three_styles]
from typing import Annotated

from pydantic import Field

from protean.core.entity import BaseEntity
from protean.fields import Float, String


class Product(BaseEntity):
    name: String(max_length=50)  # annotation
    price = Float(min_value=0)  # assignment
    metadata: Annotated[dict, Field(default_factory=dict)]  # raw Pydantic


# --8<-- [end:three_styles]

domain.init(traverse=False)
