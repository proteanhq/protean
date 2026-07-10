from . import validators
from .association import HasMany, HasOne, Reference
from .base import Field, FieldBase
from .basic import Method, Nested, ValueObjectList
from .containers import Dict, List
from .embedded import ValueObject, ValueObjectFromEntity
from .resolved import ResolvedField
from .simple import (
    Auto,
    Boolean,
    Date,
    DateTime,
    Decimal,
    Float,
    Identifier,
    Integer,
    Status,
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
    "Decimal",
    "Dict",
    # Descriptor engine backing the descriptor-style fields (associations
    # such as HasMany/HasOne/Reference, ValueObject(List), Method/Nested) and
    # the extension point for custom fields
    "Field",
    "FieldBase",
    # FieldSpec class
    "FieldSpec",
    "Float",
    # Association descriptors
    "HasMany",
    "HasOne",
    "Identifier",
    "Integer",
    "List",
    # Serializer fields
    "Method",
    "Nested",
    "Reference",
    # Resolved field metadata
    "ResolvedField",
    "Status",
    "String",
    "Text",
    "ValueObject",
    "ValueObjectFromEntity",
    "ValueObjectList",
    # Validators
    "validators",
]
