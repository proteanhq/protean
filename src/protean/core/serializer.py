"""Serializer Object Functionality and Classes"""

import logging

from marshmallow import Schema, fields

from protean.container import Element, Options, OptionsMixin
from protean.exceptions import NotSupportedError
from protean.fields import (
    Boolean,
    Date,
    DateTime,
    Dict,
    Field,
    Float,
    Identifier,
    Integer,
    List,
    Method,
    Nested,
    String,
    Text,
)
from protean.reflection import _FIELDS
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger(__name__)


def derive_marshmallow_field_from(field_obj: Field):  # noqa: C901
    if isinstance(field_obj, Boolean):
        return fields.Boolean()
    elif isinstance(field_obj, Date):
        return fields.Date()
    elif isinstance(field_obj, DateTime):
        return fields.DateTime()
    elif isinstance(field_obj, Identifier):
        return fields.String()
    elif isinstance(field_obj, String):
        return fields.String()
    elif isinstance(field_obj, Text):
        return fields.String()
    elif isinstance(field_obj, Integer):
        return fields.Integer()
    elif isinstance(field_obj, Float):
        return fields.Float()
    elif isinstance(field_obj, Method):
        return fields.Method(field_obj.method_name)
    elif isinstance(field_obj, List):
        return fields.List(
            # `field_obj.content_type` holds the class of the associated field,
            #   but this method works with objects (uses `isinstance`)
            #
            # We need to use `isinstance` because we need to pass the entire field
            #   object into this method, to be able to extract other attributes.
            #
            # So we instantiate the field in `field_obj.content_type` before calling
            #   the method.
            derive_marshmallow_field_from(field_obj.content_type())
        )
    elif isinstance(field_obj, Dict):  # FIXME Accept type param in Dict field
        return fields.Dict(keys=fields.Str())
    elif isinstance(field_obj, Nested):
        return fields.Nested(field_obj.schema_name, many=field_obj.many)
    else:
        raise NotSupportedError("{} Field not supported".format(type(field_obj)))


class _SerializerMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a Marshmellow Class meta object that can
    be used to load and dump data. It also sets up a `meta_` attribute on the Serializer to be an instance of Meta,
    either the default or one that is defined in the Serializer class.

    `meta_` is setup with these attributes:
        * `declared_fields`: A dictionary that gives a list of any instances of `Field`
            included as attributes on either the class or on any of its superclasses
    """

    def __new__(mcs, name, bases, attrs, **kwargs):  # noqa: C901
        """Initialize Serializer MetaClass and load attributes"""

        def _declared_base_class_fields(bases, attrs):
            """If this class is subclassing another Serializer, add that Serializer's
            fields.  Note that we loop over the bases in *reverse*.
            This is necessary in order to maintain the correct order of fields.
            """
            declared_fields = {}

            for base in reversed(bases):
                if hasattr(base, "meta_") and hasattr(base.meta_, "declared_fields"):
                    base_class_fields = {
                        field_name: field_obj
                        for (
                            field_name,
                            field_obj,
                        ) in fields(base).items()
                        if field_name not in attrs and not field_obj.identifier
                    }
                    declared_fields.update(base_class_fields)

            return declared_fields

        def _declared_fields(attrs):
            """Load field items into Class"""
            declared_fields = {}

            for attr_name, attr_obj in attrs.items():
                if isinstance(attr_obj, Field):
                    declared_fields[attr_name] = attr_obj

            return declared_fields

        @classmethod
        def _default_options(cls):
            return []

        # Ensure initialization is only performed for subclasses of Serializer
        # (excluding Serializer class itself).
        parents = [b for b in bases if isinstance(b, _SerializerMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Load declared fields
        declared_fields = _declared_fields(attrs)

        # Load declared fields from Base class, in case this Entity is subclassing another
        base_class_fields = _declared_base_class_fields(bases, attrs)

        all_fields = {**declared_fields, **base_class_fields}

        schema_fields = {}
        for field_name, field_obj in all_fields.items():
            schema_fields[field_name] = derive_marshmallow_field_from(field_obj)

        # Remove Protean fields from Serializer class
        for field_name in schema_fields:
            attrs.pop(field_name, None)

        # Update `attrs` with new marshmallow fields
        attrs.update(schema_fields)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base, "Meta") and hasattr(base.Meta, "abstract"):
                delattr(base.Meta, "abstract")

        # Explicit redefinition element_type  necessary because `attrs`
        #   are reset when a serializer class is initialized.
        attrs["element_type"] = DomainObjects.SERIALIZER
        attrs["_default_options"] = _default_options

        new_class = type(name, (Schema, Element, OptionsMixin), attrs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop("Meta", None)
        meta = attr_meta or getattr(new_class, "Meta", None)
        setattr(new_class, "meta_", Options(meta))

        setattr(new_class, _FIELDS, declared_fields)

        return new_class


class BaseSerializer(metaclass=_SerializerMetaclass):
    """The Base class for Protean-Compliant Serializers.

    Provides helper methods to load and dump data during runtime, from protean entity objects. Core Protean
    attributes like `element_type`, `meta_`, and `_default_options` are initialized in metaclass.

    Basic Usage::

        @Serializer
        class Address:
            unit = field.String()
            address = field.String(required=True, max_length=255)
            city = field.String(max_length=50)
            province = field.String(max_length=2)
            pincode = field.String(max_length=6)

    (or)

        class Address(BaseSerializer):
            unit = field.String()
            address = field.String(required=True, max_length=255)
            city = field.String(max_length=50)
            province = field.String(max_length=2)
            pincode = field.String(max_length=6)

        domain.register_element(Address)
    """

    def __new__(cls, *args, **kwargs):
        if cls is BaseSerializer:
            raise NotSupportedError("BaseSerializer cannot be instantiated")
        return super().__new__(cls)


def serializer_factory(element_cls, **kwargs):
    return derive_element_class(element_cls, BaseSerializer, **kwargs)
