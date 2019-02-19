"""Entity Functionality and Classes"""
import inspect
import logging
from typing import Any, Union

from protean.core.exceptions import ObjectNotFoundError
from protean.core.exceptions import ValidationError
from protean.core.field import Auto
from protean.core.field import Field
from protean.utils.query import Q

logger = logging.getLogger('protean.core.entity')

ENTITY_META_ATTRIBUTE_NAMES = ('ordering')


class EntityBase(type):
    """
    This base metaclass sets a `_meta` attribute on the Entity to an instance
    of Meta defined in the Entity

    It also sets dictionary named `declared_fields` on the `meta_` attribute.
    Any instances of `Field` included as attributes on either the class
    or on any of its superclasses will be include in this dictionary.
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize Entity Classes"""

        # Ensure initialization is only performed for subclasses of Entity
        # (excluding Entity class itself).
        parents = [b for b in bases if isinstance(b, EntityBase)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Create the class object
        module = attrs.pop('__module__')
        new_attrs = {'__module__': module}
        # Ensure we pass __classcell__ to type.__new__
        #   Refer to https://stackoverflow.com/a/41347038/1858466 for more information
        classcell = attrs.pop('__classcell__', None)
        if classcell is not None:
            new_attrs['__classcell__'] = classcell

        new_class = super().__new__(mcs, name, bases, new_attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop('Meta', None)
        meta = attr_meta or getattr(new_class, 'Meta', None)
        new_class.add_to_class('meta_', EntityMeta(meta))

        # Add declared fields
        declared_fields = []
        for attr_name, attr_obj in attrs.items():
            if isinstance(attr_obj, Field):
                new_class.add_to_class(attr_name, attr_obj)
                declared_fields.append((attr_name, attr_obj))

        # If this class is subclassing another Entity, add that Entity's
        # fields.  Note that we loop over the bases in *reverse*.
        # This is necessary in order to maintain the correct order of fields.
        for base in reversed(bases):
            if hasattr(base, 'meta_') and \
                    hasattr(base.meta_, 'declared_fields'):
                for field_name, field_obj in base.meta_.declared_fields.items():
                    if field_name not in attrs and not field_obj.identifier:
                        new_class.add_to_class(field_name, field_obj)
                        declared_fields.append((field_name, field_obj))

        # Lookup the id field for this entity
        if declared_fields:
            try:
                new_class.meta_.id_field = next(
                    field for _, field in declared_fields
                    if field.identifier)
            except StopIteration:
                # If no id field is declared then create one
                id_field = Auto(identifier=True)
                new_class.add_to_class('id', id_field)
                new_class.meta_.id_field = id_field

        # Construct an empty QuerySet associated with this Entity class
        new_class.query = QuerySet(name)

        return new_class

    def add_to_class(cls, name, value):
        """Add an attribute to the class

           Will check if `bind_to_entity` is defined on the attribute. If defined, it will
           be used to add the field to the meta class and bind the entity class to the field.
        """
        # We should call the contribute_to_class method only if it's bound
        if not inspect.isclass(value) and hasattr(value, 'bind_to_entity'):
            value.bind_to_entity(cls, name)
        else:
            setattr(cls, name, value)


class EntityMeta:
    """ Metadata information for the entity including any options defined."""

    def __init__(self, meta):
        self.meta = meta

        # Initialize Options
        self.entity_cls = None
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

    def add_field(self, field_name, field):
        """Add field to the Entity class' meta attribute"""
        self.declared_fields[field_name] = field

    def bind_to_entity(self, entity_cls, name):
        """Placeholder method for additional processing when meta info is added to Entity"""
        entity_cls.meta_ = self
        self.entity_cls = entity_cls

        # Next, apply any overridden values from 'class Meta'.
        if self.meta:
            meta_attrs = self.meta.__dict__.copy()
            for name in self.meta.__dict__:
                # Ignore any private attributes
                if name.startswith('_'):
                    del meta_attrs[name]
            for attr_name in ENTITY_META_ATTRIBUTE_NAMES:
                if attr_name in meta_attrs:
                    setattr(self, attr_name, meta_attrs.pop(attr_name))
                elif hasattr(self.meta, attr_name):
                    setattr(self, attr_name, getattr(self.meta, attr_name))

            # Any leftover attributes must be invalid.
            if meta_attrs != {}:
                raise TypeError("'class Meta' got invalid attribute(s): %s" % ','.join(meta_attrs))

        del self.meta


class QuerySet:
    """A chainable class to gather a bunch of criteria and preferences (page size, order etc.)
    before execution.

    Internally, a QuerySet can be constructed, filtered, sliced, and generally passed around
    without actually fetching data. No data fetch actually occurs until you do something
    to evaluate the queryset.

    Once evaluated, a `QuerySet` typically caches its results. If the data in the database
    might have changed, you can get updated results for the same query by calling `all()` on a
    previously evaluated `QuerySet`.

    Attributes:
        page: The current page number of the records to be pulled
        per_page: The size of each page of the records to be pulled
        order_by: The list of parameters to be used for ordering the results.
            Use a `-` before the parameter name to sort in descending order 
            and if not ascending order.
        excludes_: Objects with these properties will be excluded from the results
        filters: Filter criteria

    :return Returns a `Pagination` object that holds the query results
    """

    def __init__(self, entity_cls_name: str, criteria=None, page: int = 1, per_page: int = 10,
                 order_by: set = None):
        """Initialize either with empty preferences (when invoked on an Entity)
            or carry forward filters and preferences when chained
        """

        self._entity_cls_name = entity_cls_name
        self._criteria = criteria or Q()
        self._result_cache = None
        self._page = page or 1
        self._per_page = per_page or 10

        # `order_by` could be empty, or a string or a set.
        #   Intialize empty set if `order_by` is None
        #   Convert string to set if `order_by` is a String
        #   Safe-cast set to a set if `order_by` is already a set
        if order_by:
            self._order_by = set([order_by]) if isinstance(order_by, str) else set(order_by)
        else:
            self._order_by = set()

    def _clone(self):
        """
        Return a copy of the current QuerySet.
        """
        clone = self.__class__(self._entity_cls_name, criteria=self._criteria,
                               page=self._page, per_page=self._per_page,
                               order_by=self._order_by)
        return clone

    def _add_q(self, q_object):
        """Add a Q-object to the current filter."""
        self._criteria = self._criteria._combine(q_object, q_object.connector)

    def filter(self, *args, **kwargs):
        """
        Return a new QuerySet instance with the args ANDed to the existing
        set.
        """
        return self._filter_or_exclude(False, *args, **kwargs)

    def exclude(self, *args, **kwargs):
        """
        Return a new QuerySet instance with NOT (args) ANDed to the existing
        set.
        """
        return self._filter_or_exclude(True, *args, **kwargs)

    def _filter_or_exclude(self, negate, *args, **kwargs):
        clone = self._clone()
        if negate:
            clone._add_q(~Q(*args, **kwargs))
        else:
            clone._add_q(Q(*args, **kwargs))
        return clone

    def paginate(self, **page_args):
        """Update page preferences for query"""
        clone = self._clone()
        if 'page' in page_args and isinstance(page_args['page'], int):
            clone._page = page_args['page']
        if 'per_page' in page_args and isinstance(page_args['per_page'], int):
            clone._per_page = page_args['per_page']

        return clone

    def order_by(self, order_by: Union[set, str]):
        """Update page setting for filter set"""
        clone = self._clone()
        if isinstance(order_by, str):
            order_by = {order_by}

        clone._order_by = clone._order_by.union(order_by)

        return clone

    def _retrieve_model(self):
        """Retrieve model details associated with this Entity"""
        from protean.core.repository import repo_factory  # FIXME Move to a better placement

        # Fetch Model class and connected-adapter from Repository Factory
        model_cls = repo_factory.get_model(self._entity_cls_name)
        adapter = getattr(repo_factory, self._entity_cls_name)

        return (model_cls, adapter)

    def all(self):
        """Primary method to fetch data based on filters

        Also trigged when the QuerySet is evaluated by calling one of the following methods:
            * len()
            * bool()
            * list()
            * Iteration
            * Slicing
        """
        logger.debug(f'Query `{self.__class__.__name__}` objects with filters {self}')

        # Destroy any cached results
        self._result_cache = None

        # Fetch Model class and connected-adapter from Repository Factory
        model_cls, adapter = self._retrieve_model()

        # order_by clause must be list of keys
        order_by = model_cls.opts_.order_by if not self._order_by else self._order_by

        # Call the read method of the repository
        results = adapter._filter_objects(self._criteria, self._page, self._per_page, order_by)

        # Convert the returned results to entity and return it
        entity_items = []
        for item in results.items:
            entity_items.append(model_cls.to_entity(item))
        results.items = entity_items

        # Cache results
        self._result_cache = results

        return results

    ###############################
    # Python Magic method support #
    ###############################

    def __iter__(self):
        """Return results on iteration"""
        if self._result_cache:
            return iter(self._result_cache)

        return iter(self.all())

    def __len__(self):
        """Return length of results"""
        if self._result_cache:
            return self._result_cache.total

        return self.all().total

    def __bool__(self):
        """Return True if query results have items"""
        if self._result_cache:
            return bool(self._result_cache)

        return bool(self.all())

    def __repr__(self):
        """Support friendly print of query criteria"""
        return ("<%s: entity: %s, criteria: %s, page: %s, per_page: %s, order_by: %s>" %
                (self.__class__.__name__, self._entity_cls_name,
                 self._criteria.deconstruct(),
                 self._page, self._per_page, self._order_by))

    def __getitem__(self, k):
        """Support slicing of results"""
        if self._result_cache:
            return self._result_cache.items[k]

        return self.all().items[k]

    #########################
    # Pagination properties #
    #########################

    @property
    def total(self):
        """Return the total number of records"""
        if self._result_cache:
            return self._result_cache.total

        return self.all().total

    @property
    def items(self):
        """Return result values"""
        if self._result_cache:
            return self._result_cache.items

        return self.all().items

    @property
    def first(self):
        """Return the first result"""
        if self._result_cache:
            return self._result_cache.first

        return self.all().first

    @property
    def has_next(self):
        """Return True if there are more values present"""
        if self._result_cache:
            return self._result_cache.has_next

        return self.all().has_next

    @property
    def has_prev(self):
        """Return True if there are previous values present"""
        if self._result_cache:
            return self._result_cache.has_prev

        return self.all().has_prev


class Entity(metaclass=EntityBase):
    """The Base class for Protean-Compliant Domain Entities.

    Provides helper methods to custom define entity attributes, and query attribute names
    during runtime.

    Basic Usage::

        class Dog(Entity):
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

    During persistence, the model associated with this entity is retrieved dynamically from
            the repository factory. Model is usually initialized with a live DB connection.
    """

    class Meta:
        """Options object for an Entity.

        Acts as a placeholder for generated entity fields like:

            :declared_fields: dict
                Any instances of `Field` included as attributes on either the class 
                or on any of its superclasses will be include in this dictionary.
            :id_field: protean.core.Field
                An instance of the field that will serve as the unique identifier for the entity
        """

    def __init__(self, *template, **kwargs):
        """
        Initialise the entity object.

        During initialization, set value on fields if vaidation passes.

        This initialization technique supports keyword arguments as well as dictionaries. You
            can even use a template for initial data.
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

    def _update_data(self, *data_dict, **kwargs):
        """
        A private method to process and update entity values correctly.

        :param data: A dictionary of values to be updated for the entity
        :param kwargs: keyword arguments with key-value pairs to be updated
        """

        # Load each of the fields given in the data dictionary
        self.errors = {}

        for data in data_dict:
            if not isinstance(data, dict):
                raise AssertionError(
                    f'Positional argument "{data}" passed must be a dict.'
                    f'This argument serves as a template for loading common '
                    f'values.'
                )
            for field_name, val in data.items():
                field_obj = self.meta_.declared_fields.get(field_name, None)
                if field_obj:
                    self._setattr(field_name, field_obj, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
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
    def _retrieve_model(cls):
        """Retrieve model details associated with this Entity"""
        from protean.core.repository import repo_factory  # FIXME Move to a better placement

        # Fetch Model class and connected-adapter from Repository Factory
        model_cls = repo_factory.get_model(cls.__name__)
        adapter = getattr(repo_factory, cls.__name__)

        return (model_cls, adapter)

    ######################
    # Life-cycle methods #
    ######################

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
        results = cls.query.filter(**filters).paginate(page=1, per_page=1).all()
        if not results:
            raise ObjectNotFoundError(
                f'`{cls.__name__}` object with identifier {identifier} '
                f'does not exist.')

        # Return the first result
        return results.first

    @classmethod
    def find_by(cls, **kwargs) -> 'Entity':
        """Find a specific entity record that matches one or more criteria.

        :param kwargs: named arguments consisting of attr_name and attr_value pairs to search on
        """
        logger.debug(f'Lookup `{cls.__name__}` object with values '
                     f'{kwargs}')

        # Find this item in the repository or raise Error
        results = cls.query.filter(**kwargs).paginate(page=1, per_page=1).all()

        if not results:
            raise ObjectNotFoundError(
                f'`{cls.__name__}` object with values {[item for item in kwargs.items()]} '
                f'does not exist.')

        # Return the first result
        return results.first

    @classmethod
    def exists(cls, excludes_, **filters):
        """ Return `True` if objects matching the provided filters and excludes
        exist if not return false.

        Calls the `filter` method by default, but can be overridden for better and
            quicker implementations that may be supported by a database.

        :param excludes_: entities without this combination of field name and
            values will be returned
        """
        results = cls.query.filter(**filters).exclude(**excludes_)
        return bool(results)

    @classmethod
    def create(cls, *args, **kwargs) -> 'Entity':
        """Create a new record in the repository.

        Also performs unique validations before creating the entity

        :param args: positional arguments for the entity
        :param kwargs: keyword arguments for the entity
        """
        logger.debug(
            f'Creating new `{cls.__name__}` object using data {kwargs}')

        model_cls, adapter = cls._retrieve_model()

        # Build the entity from the input arguments
        # Raises validation errors, if any, at this point
        entity = cls(*args, **kwargs)

        # Do unique checks, create this object and return it
        entity._validate_unique()

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

    def save(self):
        """Save a new Entity into repository.

        Performs unique validations before creating the entity.
        """
        logger.debug(
            f'Creating new `{self.__class__.__name__}` object')

        values = {}
        for item in self.meta_.declared_fields.items():
            values[item[0]] = getattr(self, item[0])

        return self.__class__.create(**values)

    def update(self, *data, **kwargs) -> 'Entity':
        """Update a Record in the repository.

        Also performs unique validations before creating the entity.

        Supports both dictionary and keyword argument updates to the entity::

            dog.update({'age': 10})

            dog.update(age=10)

        :param data: Dictionary of values to be updated for the entity
        :param kwargs: keyword arguments with key-value pairs to be updated
        """
        logger.debug(f'Updating existing `{self.__class__.__name__}` object with id {self.id}')

        # Fetch Model class and connected-adapter from Repository Factory
        model_cls, adapter = self.__class__._retrieve_model()

        # Update entity's data attributes
        self._update_data(*data, **kwargs)

        # Do unique checks, update the record and return the Entity
        self._validate_unique(create=False)
        adapter._update_object(model_cls.from_entity(self))

        return self

    def _validate_unique(self, create=True):
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

        Throws ObjectNotFoundError if the object was not found in the repository
        """
        # FIXME: Return True or False to indicate an object was deleted, 
        #   rather than the count of records deleted

        # FIXME: Ensure Adapter throws ObjectNotFoundError

        # Fetch Model class and connected-adapter from Repository Factory
        _, adapter = self.__class__._retrieve_model()

        filters = {
            self.__class__.meta_.id_field.field_name: self.id
        }
        return adapter._delete_objects(**filters)
