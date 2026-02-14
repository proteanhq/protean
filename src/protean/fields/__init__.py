from .association import HasMany, HasOne, Reference
from .base import Field, FieldBase
from .basic import ValueObjectList
from .containers import Dict, List
from .embedded import ValueObject
from .simple import (
    Auto,
    Boolean,
    Date,
    DateTime,
    Float,
    Identifier,
    Integer,
    String,
    Text,
)
from .spec import FieldSpec

__all__ = [
    # FieldSpec factories (primary API)
    "Auto",
    "Boolean",
    "Date",
    "DateTime",
    "Dict",
    "Float",
    "Identifier",
    "Integer",
    "List",
    "String",
    "Text",
    # FieldSpec class
    "FieldSpec",
    # Legacy base
    "Field",
    "FieldBase",
    # Association descriptors
    "HasMany",
    "HasOne",
    "Reference",
    "ValueObject",
    "ValueObjectList",
]
