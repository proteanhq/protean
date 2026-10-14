from protean import Domain

domain = Domain(name="FieldSystem")

# isort: split

# --8<-- [start:what_you_write]
from protean.core.entity import BaseEntity
from protean.fields import Float, String


# What you write:
class Product(BaseEntity):
    name: String(max_length=50, required=True)
    price: Float(min_value=0, default=0.0)
    status: String(choices=("active", "discontinued"), default="active")


# --8<-- [end:what_you_write]

domain.init(traverse=False)
