"""Entity Functionality and Classes"""
import logging
from collections import OrderedDict
from typing import Any

from protean.core.exceptions import ObjectNotFoundError
from protean.core.exceptions import ValidationError
from protean.core.field import Auto
from protean.core.field import Field

logger = logging.getLogger('protean.core.entity')


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
    """Base class for Protean-Compliant Domain Entities

    Provides helper methods to custom define entity attributes, and query attribute names
    during runtime.

    Basic Usage::

        class Dog(Entity):
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

    """

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

    def update_data(self, data):
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
        """ Return entity data as a dictionary """
        return {field_name: getattr(self, field_name, None)
                for field_name in self.meta_.declared_fields}

    @classmethod
    def get(cls, identifier: Any) -> 'Entity':
        """Get a specific Record from the Repository

        :param identifier: id of the record to be fetched from the repository.
        """
        logger.debug(f'Lookup `{cls.__name__}` object with identifier {identifier}')
        # Get the ID field for the entity
        filters = {
            cls.meta_.id_field.field_name: identifier
        }

        # Find this item in the repository or raise Error
        results = cls.filter(page=1, per_page=1, **filters)
        if not results:
            raise ObjectNotFoundError(
                f'`{cls.__name__}` object with identifier {identifier} '
                f'does not exist.')

        # Return the first result
        return results.first

    @classmethod
    def _retrieve_model(cls):
        """Retrieve model details associated with this Entity"""
        from protean.core.repository import repo_factory  # FIXME Move to a better placement

        # Fetch Model class and connected-adapter from Repository Factory
        model_cls = repo_factory.get_model(cls.__name__)
        adapter = getattr(repo_factory, cls.__name__)

        return (model_cls, adapter)

    @classmethod
    def filter(cls, page: int = 1, per_page: int = 10, order_by: list = (),
               excludes_: dict = None, **filters) -> 'Pagination':
        """
        Read Record(s) from the repository. Method must return a `Pagination`
        object

        :param page: The current page number of the records to be pulled
        :param per_page: The size of each page of the records to be pulled
        :param order_by: The list of parameters to be used for ordering the
        results. Use a `-` before the parameter name to sort in descending
        order and if not ascending order.
        :param excludes_: Objects with these properties will be excluded
        from the results

        :return Returns a `Pagination` object that holds the filtered results
        """
        logger.debug(
            f'Query `{cls.__name__}` objects with filters {filters} and '
            f'order results by {order_by}')

        # Fetch Model class and connected-adapter from Repository Factory
        model_cls, adapter = cls._retrieve_model()

        # order_by clause must be list of keys
        order_by = model_cls.opts_.order_by if not order_by else order_by
        if not isinstance(order_by, (list, tuple)):
            order_by = [order_by]

        # default excludes to a dictionary
        excludes_ = excludes_ or {}

        # Call the read method of the repository
        results = adapter._filter_objects(page, per_page, order_by, excludes_, **filters)

        # Convert the returned results to entity and return it
        entity_items = []
        for item in results.items:
            entity_items.append(model_cls.to_entity(item))
        results.items = entity_items

        return results

    @classmethod
    def exists(cls, excludes_, **filters):
        """ Return `True` if objects matching the provided filters and excludes
        exist if not return false.

        Call the filter query by default. Can be overridden for better and
        quicker implementations.

        :param excludes_: entities without this combination of field name and
        values will be returned
        """
        results = cls.filter(page=1, per_page=1, excludes_=excludes_, **filters)
        return bool(results)

    @classmethod
    def create(cls, *args, **kwargs) -> 'Entity':
        """Create a new record in the repository"""
        logger.debug(
            f'Creating new `{cls.__name__}` object using data {kwargs}')

        model_cls, adapter = cls._retrieve_model()

        # Build the entity from the input arguments
        entity = cls(*args, **kwargs)

        # Do unique checks, create this object and return it
        entity.validate_unique()

        # Build the model object and create it
        model_obj = adapter._create_object(model_cls.from_entity(entity))

        # Update the auto fields of the entity
        for field_name, field_obj in entity.meta_.declared_fields.items():
            if isinstance(field_obj, Auto):
                if isinstance(model_obj, dict):
                    field_val = model_obj[field_name]
                else:
                    field_val = getattr(model_obj, field_name)
                setattr(entity, field_name, field_val)

        return entity

    def update(self, data: dict) -> 'Entity':
        """Update a Record in the repository

        :param identifier: The id of the record to be updated
        :param data: A dictionary of record properties to be updated
        """
        logger.debug(
            f'Updating existing `{self.__class__.__name__}` object with id '
            f'{self.id} using data {data}')

        # Fetch Model class and connected-adapter from Repository Factory
        model_cls, adapter = self.__class__._retrieve_model()

        # Update entity's data attributes
        self.update_data(data)

        # Do unique checks, update the record and return the Entity
        self.validate_unique(create=False)
        adapter._update_object(model_cls.from_entity(self))

        return self

    def validate_unique(self, create=True):
        """ Validate the unique constraints for the entity """
        # Fetch Model class and connected-adapter from Repository Factory
        model_cls, _ = self.__class__._retrieve_model()

        # Build the filters from the unique constraints
        filters, excludes = {}, {}

        for field_name, field_obj in self.meta_.unique_fields:
            lookup_value = getattr(self, field_name, None)
            # Ignore empty lookup values
            if lookup_value in Field.empty_values:
                continue
            # Ignore identifiers on updates
            if not create and field_obj.identifier:
                excludes[field_name] = lookup_value
                continue
            filters[field_name] = lookup_value

        # Lookup the objects by the filters and raise error on results
        for filter_key, lookup_value in filters.items():
            if self.exists(excludes, **{filter_key: lookup_value}):
                field_obj = self.meta_.declared_fields[filter_key]
                field_obj.fail('unique',
                               model_name=model_cls.opts_.model_name,
                               field_name=filter_key)

    def delete(self):
        """Delete a Record from the Repository

        FIXME: Return True or False to indicate an object was deleted,
               rather than the count of records deleted
        """
        # Fetch Model class and connected-adapter from Repository Factory
        _, adapter = self.__class__._retrieve_model()

        filters = {
            self.__class__.meta_.id_field.field_name: self.id
        }
        return adapter._delete_objects(**filters)
