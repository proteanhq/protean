"""Module for defining the ValueObjectList field descriptor and backward-compat re-exports"""

import datetime

from protean.exceptions import ValidationError
from protean.fields import Field
from protean.fields.embedded import ValueObject

# Re-export FieldSpec factory functions for backward compatibility.
# Old code uses ``from protean.fields.basic import String, Integer, ...``
from protean.fields.containers import Dict, List
from protean.fields.simple import (
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

# Supported Python types for List content_type
_SUPPORTED_CONTENT_TYPES = (
    bool,
    datetime.date,
    datetime.datetime,
    float,
    int,
    str,
    dict,
)


class ValueObjectList(Field):
    """
    A field that represents a list of values.

    :param content_type: The Python type of items in the list (e.g., str, int, float),
        or a ValueObject descriptor for lists of value objects.
    :type content_type: type or ValueObject
    :param pickled: Whether the list should be pickled when stored, defaults to False.
    :type pickled: bool, optional
    """

    default_error_messages = {
        "invalid": '"{value}" value must be of list type.',
        "invalid_content": "Invalid value {value}",
    }

    def __init__(self, content_type=str, pickled=False, **kwargs):
        if content_type not in _SUPPORTED_CONTENT_TYPES and not isinstance(
            content_type, ValueObject
        ):
            raise ValidationError({"content_type": ["Content type not supported"]})
        self.content_type = content_type
        self.pickled = pickled

        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """Raise errors if the value is not a list, or
        the items in the list are not of the right data type.
        """
        if not isinstance(value, list):
            self.fail("invalid", value=value)

        if isinstance(self.content_type, ValueObject):
            new_value = []
            try:
                for item in value:
                    new_value.append(self.content_type._load(item))
            except ValidationError:
                self.fail("invalid_content", value=value)
            return new_value

        # For Python primitive types, cast each item
        new_value = []
        try:
            for item in value:
                new_value.append(self.content_type(item))
        except (ValueError, TypeError):
            self.fail("invalid_content", value=value)
        return new_value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        if isinstance(self.content_type, ValueObject):
            return [self.content_type.as_dict(item) for item in value]

        # For primitive types, convert datetime/date to strings
        if self.content_type in (datetime.date, datetime.datetime):
            return [str(item) if item else None for item in value]

        return list(value)


class Method(Field):
    """Helper field for custom methods associated with serializer fields"""

    def __init__(self, method_name, **kwargs):
        self.method_name = method_name
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """Perform no validation for Method fields. Return the value as is"""
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return value


class Nested(Field):
    """Helper field for nested objects associated with serializer fields"""

    def __init__(self, schema_name, many=False, **kwargs):
        self.schema_name = schema_name
        self.many = many
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """Perform no validation for Nested fields. Return the value as is"""
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return value

    def __repr__(self):
        values = []
        if self.schema_name:
            values.append(f"'{self.schema_name}'")
        if self.many:
            values.append(f"many={self.many}")
        return f"Nested({', '.join(values)})"


__all__ = [
    "Auto",
    "Boolean",
    "Date",
    "DateTime",
    "Dict",
    "Float",
    "Identifier",
    "Integer",
    "List",
    "Method",
    "Nested",
    "String",
    "Text",
    "ValueObjectList",
]
