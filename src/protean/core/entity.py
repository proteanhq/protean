"""Entity Functionality and Classes"""
from collections import OrderedDict

from protean.core.field import Field, Auto
from protean.core.exceptions import ValidationError


class EntityBase(type):
    """
    This base metaclass sets a `_meta` attribute on the Entity to an instance
    of Meta defined in the Entity

    It also sets dictionary named `declared_fields` on the `_meta` attribute.
    Any instances of `Field` included as attributes on either the class
    or on any of its superclasses will be include in this dictionary.
    """

    @classmethod
    def _get_declared_fields(mcs, klass, bases, attrs):
        # Load all attributes of the class that are instances of `Field`
        fields = []
        for attr_name, attr_obj in attrs.items():
            if isinstance(attr_obj, Field):
                # Bind the field object and append to list
                attr_obj.bind_to_entity(klass, attr_name)
                fields.append((attr_name, attr_obj))

        # If this class is subclassing another Entity, add that Entity's
        # fields.  Note that we loop over the bases in *reverse*.
        # This is necessary in order to maintain the correct order of fields.
        for base in reversed(bases):
            if hasattr(base, 'meta_') and \
                    hasattr(base.meta_, 'declared_fields'):
                fields = [
                    (field_name, field_obj) for field_name, field_obj
                    in base.meta_.declared_fields.items()
                    if field_name not in attrs and not field_obj.identifier
                ] + fields

        return OrderedDict(fields)

    def __new__(mcs, name, bases, attrs):
        klass = super(EntityBase, mcs).__new__(mcs, name, bases, attrs)
        declared_fields = mcs._get_declared_fields(klass, bases, attrs)

        klass.meta_ = EntityMeta(getattr(klass, 'Meta'), klass)
        klass.meta_.declared_fields = declared_fields

        # Lookup the id field for this entity
        if declared_fields:
            try:
                klass.meta_.id_field = next(
                    field for _, field in declared_fields.items()
                    if field.identifier)
            except StopIteration:
                # If no id field is declared then create one
                klass.meta_.id_field = Auto(identifier=True)
                klass.meta_.id_field.bind_to_entity(klass, 'id')
                declared_fields['id'] = klass.meta_.id_field

        return klass


class EntityMeta:
    """ Metadata information for the entity including any options defined."""

    def __init__(self, meta, entity_cls):
        self.entity_cls = entity_cls
        self.declared_fields = {}
        self.id_field = None

    @property
    def unique_fields(self):
        """ Return the unique fields for this entity """
        return [(field_name, field_obj)
                for field_name, field_obj in self.declared_fields.items()
                if field_obj.unique]

    @property
    def has_auto_field(self):
        """ Check the the id_field for the entity is Auto Type"""
        return any([isinstance(field_obj, Auto) for
                    _, field_obj in self.declared_fields.items()])


class Entity(metaclass=EntityBase):
    """Class for defining Domain Entities"""

    class Meta:
        """Options object for an Entity"""

    def __init__(self, *template, **kwargs):
        """
        Initialise the entity object perform the validations on each of
        the fields and set its value on passing. This initialization technique
        supports keyword arguments as well as dictionaries. You can even use
        a template for initial data.
        """

        self.errors = {}

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
                field_obj = self.meta_.declared_fields.get(field_name, None)
                if field_obj:
                    loaded_fields.append(field_name)
                    self._setattr(field_name, field_obj, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            field_obj = self.meta_.declared_fields.get(field_name, None)
            if field_obj:
                loaded_fields.append(field_name)
                self._setattr(field_name, field_obj, val)

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in self.meta_.declared_fields.items():
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

    def update(self, data):
        """
        Update the entity with the given set of values
        :param data: the dictionary of values to be updated for the entity
        """

        # Load each of the fields given in the data dictionary
        self.errors = {}
        for field_name, val in data.items():
            field_obj = self.meta_.declared_fields.get(field_name, None)
            if field_obj:
                self._setattr(field_name, field_obj, val)

        # Raise any errors found during update
        if self.errors:
            raise ValidationError(self.errors)

    def to_dict(self):
        """ Convert the entity to a dictionary """
        return {field_name: getattr(self, field_name, None)
                for field_name in self.meta_.declared_fields}
