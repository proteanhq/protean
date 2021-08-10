"""Serializer Object Functionality and Classes"""
import logging

from marshmallow import Schema, fields

from protean.core.field.basic import (
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
from protean.exceptions import NotSupportedError
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger("protean.application.serializer")


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
                        ) in base.meta_.declared_fields.items()
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
            if isinstance(field_obj, Boolean):
                schema_fields[field_name] = fields.Boolean()
            elif isinstance(field_obj, Date):
                schema_fields[field_name] = fields.Date()
            elif isinstance(field_obj, DateTime):
                schema_fields[field_name] = fields.DateTime()
            elif isinstance(field_obj, Identifier):
                schema_fields[field_name] = fields.String()
            elif isinstance(field_obj, String):
                schema_fields[field_name] = fields.String()
            elif isinstance(field_obj, Text):
                schema_fields[field_name] = fields.String()
            elif isinstance(field_obj, Integer):
                schema_fields[field_name] = fields.Integer()
            elif isinstance(field_obj, Float):
                schema_fields[field_name] = fields.Float()
            elif isinstance(field_obj, Method):
                schema_fields[field_name] = fields.Method(field_obj.method_name)
            elif isinstance(field_obj, List):
                schema_fields[field_name] = fields.List(
                    fields.String()
                )  # FIXME Accept type param in List field
            elif isinstance(field_obj, Dict):  # FIXME Accept type param in Dict field
                schema_fields[field_name] = fields.Dict(keys=fields.Str())
            elif isinstance(field_obj, Nested):
                schema_fields[field_name] = fields.Nested(
                    field_obj.schema_name, many=field_obj.many
                )
            else:
                raise NotSupportedError(
                    "{} Field not supported".format(type(field_obj))
                )

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

        new_class = type(name, (Schema,), attrs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop("Meta", None)
        meta = attr_meta or getattr(new_class, "Meta", None)
        setattr(new_class, "meta_", SerializerMeta(meta, declared_fields))

        return new_class


class SerializerMeta:
    """ Metadata info for the Serializer.

    Also acts as a placeholder for generated entity fields like:

        :declared_fields: dict
            Any instances of `Field` included as attributes on either the class
            or on any of its superclasses will be include in this dictionary.
    """

    def __init__(self, meta, declared_fields):
        self.aggregate_cls = getattr(meta, "aggregate_cls", None)

        # Initialize Options
        self.declared_fields = declared_fields if declared_fields else {}


class BaseSerializer(metaclass=_SerializerMetaclass):
    """The Base class for Protean-Compliant Serializers.

    Provides helper methods to load and dump data during runtime, from protean entity objects.

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
            raise TypeError("BaseSerializer cannot be instantiated")
        return super().__new__(cls)


def serializer_factory(element_cls, **kwargs):
    return derive_element_class(element_cls, BaseSerializer)
