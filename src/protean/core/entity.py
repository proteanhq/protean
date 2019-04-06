"""Entity Functionality and Classes"""
import copy
import logging
from typing import Any
from typing import Union

from protean.core.exceptions import ObjectNotFoundError
from protean.core.exceptions import ValidationError
from protean.core.field import Auto
from protean.core.field import Field
from protean.core.field import Reference
from protean.core.field import ReferenceField
from protean.core.repository import repo_factory
from protean.utils.query import Q

logger = logging.getLogger('protean.core.entity')


class EntityBase(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the Entity class later. Specifically, it sets up a `meta_` attribute on
    the Entity to an instance of Meta, either the default of one that is defined in the
    Entity class.

    `meta_` is setup with these attributes:
        * `declared_fields`: A dictionary that gives a list of any instances of `Field`
            included as attributes on either the class or on any of its superclasses
        * `id_field`: The Primary identifier attribute of the Entity
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize Entity MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of Entity
        # (excluding Entity class itself).
        parents = [b for b in bases if isinstance(b, EntityBase)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop('Meta', None)
        meta = attr_meta or getattr(new_class, 'Meta', None)
        setattr(new_class, 'meta_', EntityMeta(meta))

        # Load declared fields
        new_class._load_fields(attrs)

        # Load declared fields from Base class, in case this Entity is subclassing another
        new_class._load_base_class_fields(bases, attrs)

        # Lookup an already defined ID field or create an `Auto` field
        new_class._set_id_field()

        # Set up Relation Fields
        new_class._set_up_reference_fields()

        # Load list of Attributes from declared fields, depending on type of fields
        new_class._load_attributes()

        return new_class

    @property
    def query(cls):
        """Construct an empty QuerySet associated with an Entity class
            everytime a new `query` object is created

        This is required so as not to corrupt the query object associated with the metaclass
        when invoked like `Dog.query.all()` directly. A new query, and a corresponding `Pagination`
        result would be created every time.
        """
        return QuerySet(cls)

    def _load_base_class_fields(new_class, bases, attrs):
        """If this class is subclassing another Entity, add that Entity's
        fields.  Note that we loop over the bases in *reverse*.
        This is necessary in order to maintain the correct order of fields.
        """
        for base in reversed(bases):
            if hasattr(base, 'meta_') and \
                    hasattr(base.meta_, 'declared_fields'):
                base_class_fields = {
                    field_name: field_obj for (field_name, field_obj)
                    in base.meta_.declared_fields.items()
                    if field_name not in attrs and not field_obj.identifier
                }
                new_class._load_fields(base_class_fields)

    def _load_fields(new_class, attrs):
        """Load field items into Class.

        This method sets up the primary attribute of an association.
        If Child class has defined an attribute so `parent = field.Reference(Parent)`, then `parent`
        is set up in this method, while `parent_id` is set up in `_set_up_reference_fields()`.
        """
        for attr_name, attr_obj in attrs.items():
            if isinstance(attr_obj, (Field, Reference)):
                setattr(new_class, attr_name, attr_obj)
                new_class.meta_.declared_fields[attr_name] = attr_obj

    def _set_up_reference_fields(new_class):
        """Walk through relation fields and setup shadow attributes"""
        if new_class.meta_.declared_fields:
            for _, field in new_class.meta_.declared_fields.items():
                if isinstance(field, Reference):
                    shadow_field_name, shadow_field = field.get_shadow_field()
                    setattr(new_class, shadow_field_name, shadow_field)
                    shadow_field.__set_name__(new_class, shadow_field_name)

    def _set_id_field(new_class):
        """Lookup the id field for this entity and assign"""
        # FIXME What does it mean when there are no declared fields?
        #   Does it translate to an abstract entity?
        if new_class.meta_.declared_fields:
            try:
                new_class.meta_.id_field = next(
                    field for _, field in new_class.meta_.declared_fields.items()
                    if field.identifier)
            except StopIteration:
                # If no id field is declared then create one
                new_class._create_id_field()

    def _create_id_field(new_class):
        """Create and return a default ID field that is Auto generated"""
        id_field = Auto(identifier=True)

        setattr(new_class, 'id', id_field)
        id_field.__set_name__(new_class, 'id')

        # Ensure ID field is updated properly in Meta attribute
        new_class.meta_.declared_fields['id'] = id_field
        new_class.meta_.id_field = id_field

    def _load_attributes(new_class):
        """Load list of attributes from declared fields"""
        for field_name, field_obj in new_class.meta_.declared_fields.items():
            new_class.meta_.attributes[field_obj.get_attribute_name()] = field_obj


class EntityMeta:
    """ Metadata information for the entity including any options defined."""

    def __init__(self, meta):
        self.meta = meta

        # Initialize Options
        self.entity_cls = None
        self.declared_fields = {}
        self.attributes = {}
        self.id_field = None

    @property
    def unique_fields(self):
        """ Return the unique fields for this entity """
        return [(field_name, field_obj)
                for field_name, field_obj in self.declared_fields.items()
                if field_obj.unique]

    @property
    def auto_fields(self):
        return [(field_name, field_obj)
                for field_name, field_obj in self.declared_fields.items()
                if isinstance(field_obj, Auto)]


class EntityStateFieldsCacheDescriptor:
    def __get__(self, instance, cls=None):
        if instance is None:
            return self
        res = instance.fields_cache = {}
        return res


class EntityState:
    """Store entity instance state."""

    def __init__(self):
        self._new = True
        self._changed = False
        self._destroyed = False

    @property
    def is_new(self):
        return self._new

    @property
    def is_persisted(self):
        return not self._new

    @property
    def is_changed(self):
        return self._changed

    @property
    def is_destroyed(self):
        return self._destroyed

    def mark_saved(self):
        self._new = False
        self._changed = False

    mark_retrieved = mark_saved  # Alias as placeholder so that future change wont affect interface

    def mark_changed(self):
        if not (self._new or self._destroyed):
            self._changed = True

    def mark_destroyed(self):
        self._destroyed = True
        self._changed = False

    fields_cache = EntityStateFieldsCacheDescriptor()


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

        # Set up the storage for instance state
        self.state_ = EntityState()

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
                loaded_fields.append(field_name)
                setattr(self, field_name, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            loaded_fields.append(field_name)
            setattr(self, field_name, val)

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in self.meta_.declared_fields.items():
            if field_name not in loaded_fields:
                if not isinstance(field_obj, (Reference, ReferenceField)):
                    setattr(self, field_name, None)

        # Raise any errors found during load
        if self.errors:
            raise ValidationError(self.errors)

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
                setattr(self, field_name, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            setattr(self, field_name, val)

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

        # Fetch Model class and connected repository from Repository Factory
        model_cls = repo_factory.get_model(cls)
        repository = repo_factory.get_repository(cls)

        return (model_cls, repository)

    def clone(self):
        """Deepclone the entity, but reset state"""
        clone_copy = copy.deepcopy(self)
        clone_copy.state_ = EntityState()

        return clone_copy

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

        model_cls, repository = cls._retrieve_model()

        try:
            # Build the entity from the input arguments
            # Raises validation errors, if any, at this point
            entity = cls(*args, **kwargs)

            # Do unique checks, create this object and return it
            entity._validate_unique()

            # Build the model object and create it
            model_obj = repository._create_object(model_cls.from_entity(entity))

            # Update the auto fields of the entity
            for field_name, field_obj in entity.meta_.declared_fields.items():
                if isinstance(field_obj, Auto):
                    if isinstance(model_obj, dict):
                        field_val = model_obj[field_name]
                    else:
                        field_val = getattr(model_obj, field_name)
                    setattr(entity, field_name, field_val)

            # Set Entity status to saved
            entity.state_.mark_saved()

            return entity
        except ValidationError as exc:
            # FIXME Log Exception
            raise

    def save(self):
        """Save a new Entity into repository.

        Performs unique validations before creating the entity.
        """
        logger.debug(
            f'Saving `{self.__class__.__name__}` object')

        # Fetch Model class and connected repository from Repository Factory
        model_cls, repository = self.__class__._retrieve_model()

        try:
            # Do unique checks, update the record and return the Entity
            self._validate_unique(create=False)

            # Build the model object and create it
            model_obj = repository._create_object(model_cls.from_entity(self))

            # Update the auto fields of the entity
            for field_name, field_obj in self.meta_.declared_fields.items():
                if isinstance(field_obj, Auto):
                    if isinstance(model_obj, dict):
                        field_val = model_obj[field_name]
                    else:
                        field_val = getattr(model_obj, field_name)
                    setattr(self, field_name, field_val)

            # Set Entity status to saved
            self.state_.mark_saved()

            return self
        except Exception as exc:
            # FIXME Log Exception
            raise

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

        # Fetch Model class and connected repository from Repository Factory
        model_cls, repository = self.__class__._retrieve_model()

        try:
            # Update entity's data attributes
            self._update_data(*data, **kwargs)

            # Do unique checks, update the record and return the Entity
            self._validate_unique(create=False)
            repository._update_object(model_cls.from_entity(self))

            # Set Entity status to saved
            self.state_.mark_saved()

            return self
        except Exception as exc:
            # FIXME Log Exception
            raise

    def _validate_unique(self, create=True):
        """ Validate the unique constraints for the entity """
        # Fetch Model class and connected-repository from Repository Factory
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

        will perform callbacks and run validations before deletion.

        Throws ObjectNotFoundError if the object was not found in the repository.
        """
        # Fetch Model class and connected repository from Repository Factory
        model_cls, repository = self.__class__._retrieve_model()

        try:
            if not self.state_.is_destroyed:
                # Update entity's data attributes
                repository._delete_object(model_cls.from_entity(self))

                # Set Entity status to saved
                self.state_.mark_destroyed()

            return self
        except Exception as exc:
            # FIXME Log Exception
            raise


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

    def __init__(self, entity_cls: Entity, criteria=None, page: int = 1, per_page: int = 10,
                 order_by: set = None):
        """Initialize either with empty preferences (when invoked on an Entity)
            or carry forward filters and preferences when chained
        """

        self._entity_cls = entity_cls
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
        clone = self.__class__(self._entity_cls, criteria=self._criteria,
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
        # Fetch Model class and connected repository from Repository Factory
        model_cls = repo_factory.get_model(self._entity_cls)
        repository = repo_factory.get_repository(self._entity_cls)

        return (model_cls, repository)

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

        # Fetch Model class and connected repository from Repository Factory
        model_cls, repository = self._retrieve_model()

        # order_by clause must be list of keys
        order_by = model_cls.opts_.order_by if not self._order_by else self._order_by

        # Call the read method of the repository
        results = repository._filter_objects(self._criteria, self._page, self._per_page, order_by)

        # Convert the returned results to entity and return it
        entity_items = []
        for item in results.items:
            entity = model_cls.to_entity(item)
            entity.state_.mark_retrieved()
            entity_items.append(entity)
        results.items = entity_items

        # Cache results
        self._result_cache = results

        return results

    def update(self, *data, **kwargs):
        """Updates all objects with details given if they match a set of conditions supplied.

        This method updates each object individually, to fire callback methods and ensure
        validations are run.

        Returns the number of objects matched (which may not be equal to the number of objects
            updated if objects rows already have the new value).
        """
        updated_item_count = 0
        try:
            items = self.all()

            for item in items:
                item.update(*data, **kwargs)
                updated_item_count += 1
        except Exception as exc:
            # FIXME Log Exception
            raise

        return updated_item_count

    def delete(self):
        """Deletes matching objects from the Repository

        Does not throw error if no objects are matched.

        Returns the number of objects matched (which may not be equal to the number of objects
            deleted if objects rows already have the new value).
        """
        # Fetch Model class and connected repository from Repository Factory
        deleted_item_count = 0
        try:
            items = self.all()

            for item in items:
                item.delete()
                deleted_item_count += 1
        except Exception as exc:
            # FIXME Log Exception
            raise

        return deleted_item_count

    def update_all(self, *args, **kwargs):
        """Updates all objects with details given if they match a set of conditions supplied.

        This method forwards filters and updates directly to the repository. It does not
        instantiate entities and it does not trigger Entity callbacks or validations.

        Update values can be specified either as a dict, or keyword arguments.

        Returns the number of objects matched (which may not be equal to the number of objects
            updated if objects rows already have the new value).
        """
        updated_item_count = 0
        _, repository = self._retrieve_model()
        try:
            updated_item_count = repository._update_all_objects(self._criteria, *args, **kwargs)
        except Exception as exc:
            # FIXME Log Exception
            raise

        return updated_item_count

    def delete_all(self, *args, **kwargs):
        """Deletes objects that match a set of conditions supplied.

        This method forwards filters directly to the repository. It does not instantiate entities and
        it does not trigger Entity callbacks or validations.

        Returns the number of objects matched and deleted.
        """
        deleted_item_count = 0
        _, repository = self._retrieve_model()
        try:
            deleted_item_count = repository._delete_all_objects(self._criteria)
        except Exception as exc:
            # FIXME Log Exception
            raise

        return deleted_item_count

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
                (self.__class__.__name__, self._entity_cls,
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
