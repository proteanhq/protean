"""This module holds the generic definitions of Serializer"""

from collections import OrderedDict

import marshmallow as ma

from protean.core import field
from protean.core.entity import Entity
from protean.core.exceptions import ConfigurationError


class BaseSerializer(ma.Schema):
    """Base serializer with which to define custom serializers."""


class EntitySerializerOpts(ma.schema.SchemaOpts):
    """ Options for the entity serializer"""
    def __init__(self, meta):
        super().__init__(meta)
        self.entity_cls = getattr(meta, 'entity', None)


class EntitySerializer(BaseSerializer):
    """Serializer which uses Entity class to automatically infer fields."""

    OPTIONS_CLASS = EntitySerializerOpts

    field_mapping = {
        field.String: ma.fields.String,
        field.Boolean: ma.fields.Boolean,
        field.Integer: ma.fields.Integer,
        field.Float: ma.fields.Float,
        field.List: ma.fields.List,
        field.Dict: ma.fields.Dict,
        field.Auto: ma.fields.Integer
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Updates the declared fields with the fields of the Entity class
        if not self.opts.entity_cls or not \
                issubclass(self.opts.entity_cls, Entity):
            raise ConfigurationError(
                '`Meta.entity` option must be set and a subclass of `Entity`.')

        entity_fields = OrderedDict()
        for field_name, field_obj in \
                self.opts.entity_cls.meta_.declared_fields.items():
            if self.opts.fields and field_name not in self.opts.fields:
                continue
            elif self.opts.exclude and field_name in self.opts.exclude:
                continue
            elif isinstance(field_obj, field.Reference):
                continue
            elif field_name not in self.declared_fields:
                entity_fields[field_name] = self.build_field(field_obj)

        self.declared_fields.update(entity_fields)

    def build_field(self, field_obj):
        """ Map the Entity field to a Marshmallow field """

        # Lookup the field mapping in the dictionary, default to String field
        e_field_type = type(field_obj)
        if e_field_type in self.field_mapping:
            field_opts = {}
            if e_field_type == field.List:
                field_opts['cls_or_instance'] = ma.fields.String
            return self.field_mapping[e_field_type](**field_opts)
        else:
            return ma.fields.String()
