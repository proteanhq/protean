"""Entity Functionality and Classes"""
import copy

from collections import OrderedDict

from protean.core.field import Field
from protean.core.exceptions import ValidationError, ConfigurationError


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

    @classmethod
    def _get_id_field(mcs, fields):
        """ Method to find the identifier field for this entity. Raises
        `ConfigurationError` if no identifier is defined"""
        try:
            id_field = next(field_name for field_name, field in fields.items()
                            if field.identifier)
            return id_field
        except StopIteration:
            raise ConfigurationError(
                'Identifier field must be defined for an Entity.')

    def __new__(mcs, name, bases, attrs):
        attrs['_declared_fields'] = mcs._get_declared_fields(bases, attrs)
        # Set the id field only when an entity has declared fields
        if attrs['_declared_fields']:
            attrs['id_field'] = mcs._get_id_field(attrs['_declared_fields'])
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
        self.declared_fields = self.get_fields()

        # Load the attributes based on the template
        loaded_fields = []
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f'Positional argument "{dictionary}" passed must be a dict.'
                    f'This argument serves as a template for loading common '
                    f'values.'
                )
            for field_name, val in dictionary.items():
                field_obj = self.declared_fields.get(field_name, None)
                if field_obj:
                    loaded_fields.append(field_name)
                    self._setattr(field_name, field_obj, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            field_obj = self.declared_fields.get(field_name, None)
            if field_obj:
                loaded_fields.append(field_name)
                self._setattr(field_name, field_obj, val)

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in self.declared_fields.items():
            if field_name not in loaded_fields:
                self._setattr(field_name, field_obj, None)

        # Raise any errors found during load
        if self.errors:
            raise ValidationError(self.errors)

    def _setattr(self, field_name, field_obj, value):
        """
        Load the value for the field, set it if passes and if not
        add to the error list.
        """
        try:
            valid_value = field_obj.load(value)
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

    def update(self, data):
        """
        Update the entity with the given set of values
        :param data: the dictionary of values to be updated for the entity
        """

        # Load each of the fields given in the data dictionary
        self.errors = {}
        for field_name, val in data.items():
            field_obj = self.declared_fields.get(field_name, None)
            if field_obj:
                self._setattr(field_name, field_obj, val)

        # Raise any errors found during update
        if self.errors:
            raise ValidationError(self.errors)
