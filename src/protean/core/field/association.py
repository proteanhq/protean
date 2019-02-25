from .base import Field
from .basic import Integer
from .mixins import FieldCacheMixin

from protean.core import exceptions


class ReferenceField(Integer):  # FIXME Can be either Int or Str - should allow in future
    """Shadow Attribute Field to back References"""

    def __init__(self, reference, **kwargs):
        """Accept reference field as a an attribute, otherwise is a straightforward field"""
        self.reference = reference
        super().__init__(**kwargs)

    def __set__(self, instance, value):
        """Override `__set__` to update relation field"""
        value = self._load(value)

        if value:
            instance.__dict__[self.field_name] = value

            # Fetch target object and refresh the reference field value
            reference_obj = self.reference.to_cls.get(value)
            if reference_obj:
                self.reference.value = reference_obj
                instance.__dict__[self.reference.field_name] = reference_obj
            else:
                # Object was not found in the database
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

    def get_attribute_name(self):
        """Return attribute name suffixed with `_id`"""
        return self.field_name + "_id"

    def get_shadow_field(self):
        """Return shadow field
        Primarily used during Entity initialization to register shadow field"""
        return (self.attribute_name, self.relation)

    def __set__(self, instance, value):
        """Override `__set__` to coordinate between relation field and its shadow attribute"""
        value = self._load(value)

        if value:
            # Check if the reference object has been saved. Otherwise, throw ValueError
            if value.id is None:  # FIXME not a comprehensive check. Should refer to state
                raise exceptions.ValueError(
                    "Target Object must be saved before being referenced",
                    self.field_name)
            else:
                instance.__dict__[self.field_name] = value
                instance.__dict__[self.attribute_name] = value.id

    def _cast_to_type(self, value):
        if not isinstance(value, self.to_cls):
            self.fail('invalid', value=value)
        return value

    def get_cache_name(self):
        return self.name
