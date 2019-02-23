from .base import Field
from .basic import Integer
from .mixins import FieldCacheMixin

from protean.core import exceptions


class ReferenceField(Integer):  # FIXME Can be either Int or Str - should allow in future
    """Shadow Attribute Field to back References"""

    def __init__(self, reference, **kwargs):
        self.reference = reference
        super().__init__(**kwargs)

    def __set__(self, instance, value):
        value = self._load(value)

        if value:
            setattr(instance, self.name, value)
            reference_obj = self.reference.to_cls.get(value)
            if reference_obj:
                self.reference.value = reference_obj
            else:
                raise exceptions.ValueError(
                    "Target Object not found",
                    self.reference.field_name)


class Reference(FieldCacheMixin, Field):
    """
    Provide a many-to-one relation by adding a column to the local entity
    to hold the remote value.

    By default ForeignKey will target the pk of the remote model but this
    behavior can be changed by using the ``via`` argument.
    """

    def __init__(self, to_cls, via=None, **kwargs):
        super().__init__(**kwargs)
        self.to_cls = to_cls
        self.via = via

        self.relation = ReferenceField(self)

    def __set_name__(self, entity_cls, name):
        """Set up attributes to identify relation by"""

        # Call `Field`'s set_name so that all attributes are initialized
        super().__set_name__(entity_cls, name)

        self.name = name + "__raw"
        self.field_name = name
        self.attribute_name = self.get_attribute_name()

        # `self.label` should default to being based on the field name.
        if self.label is None:
            self.label = self.field_name.replace('_', ' ').capitalize()

    def get_attribute_name(self):
        """Return Attribute name for the attribute.

        Defaults to the field name in this base class, but can be overridden.
        Handy when defining complex objects with shadow attributes, like Foreign keys.
        """
        return self.field_name + "_id"

    def get_relation_field(self):
        """Return shadow field"""
        return (self.attribute_name, self.relation)

    def __get__(self, instance, owner):
        return getattr(instance, self.name, self.value)

    def __set__(self, instance, value):
        value = self._load(value)

        if value:
            if value.id is None:
                raise exceptions.ValueError(
                    "Target Object must be saved before being referenced",
                    self.field_name)
            else:
                setattr(instance, self.name, value)
                setattr(instance, self.attribute_name, value.id)

    def _cast_to_type(self, value):
        if not isinstance(value, self.to_cls):
            self.fail('invalid', value=value)
        return value

    def get_cache_name(self):
        return self.name
