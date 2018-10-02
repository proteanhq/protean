"""Entity Functionality and Classes"""
import copy

from collections import OrderedDict

from protean.core.field import Field
from protean.core.exceptions import ValidationError


class EntityBase(type):
    """
    This base metaclass sets a dictionary named `_declared_fields` on the class.
    Any instances of `Field` included as attributes on either the class
    or on any of its superclasses will be include in the
    `_declared_fields` dictionary.
    """

    @classmethod
    def _get_declared_fields(mcs, bases, attrs):
        # Load all attributes of the class that are instances of `Field`
        fields = []
        for attr_name, attr_obj in attrs.items():
            if isinstance(attr_obj, Field):
                # Bind the field object and append to list
                attr_obj.bind(attr_name)
                fields.append((attr_name, attr_obj))

        # If this class is subclassing another Entity, add that Entity's
        # fields.  Note that we loop over the bases in *reverse*.
        # This is necessary in order to maintain the correct order of fields.
        for base in reversed(bases):
            if hasattr(base, '_declared_fields'):
                fields = [
                    (field_name, field_obj) for field_name, field_obj
                    in base._declared_fields.items()
                    if field_name not in attrs
                ] + fields

        return OrderedDict(fields)

    def __new__(mcs, name, bases, attrs):
        attrs['_declared_fields'] = mcs._get_declared_fields(bases, attrs)
        return super(EntityBase, mcs).__new__(mcs, name, bases, attrs)


class Entity(metaclass=EntityBase):
    """Class for defining Domain Entities"""
    _declared_fields = {}

    def __init__(self, *template, **kwargs):
        """
        Initialise the entity object perform the validations on each of
        the fields and set its value on passing. This initialization technique
        supports keyword arguments as well as dictionaries. You can even use
        a template for initial data.
        """

        self.errors = {}
        fields = self.get_fields()

        # Load the attributes based on the template
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f'Positional argument "{dictionary}" passed must be a dict.'
                    f'This argument serves as a template for loading common '
                    f'values.'
                )
            for field_name, val in dictionary.items():
                field_obj = fields.pop(field_name, None)
                if field_obj:
                    self._setattr(field_name, field_obj, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            field_obj = fields.pop(field_name, None)
            if field_obj:
                self._setattr(field_name, field_obj, val)

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in fields.items():
            self._setattr(field_name, field_obj, None)

        # Raise any errors found during load
        if self.errors:
            raise ValidationError(self.errors)

    def _setattr(self, field_name, field_obj, value):
        """
        Validate the value for the field, set it if passes if not
        return the error.
        """
        try:
            valid_value = field_obj.validate(value)
            setattr(self, field_name, valid_value)
        except ValidationError as err:
            self.errors[field_name] = err.messages

    def get_fields(self):
        """
        Returns a dictionary of {field_name: field_instance}.
        """
        # Every new entity is created with a clone of the field instances.
        # This allows users to dynamically modify the fields on a entity
        # instance without affecting every other entity instance.

        return copy.deepcopy(self._declared_fields)
