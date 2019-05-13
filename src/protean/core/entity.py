"""Entity Functionality and Classes"""
# Standard Library Imports
import copy
import logging

from typing import Any
from uuid import uuid4

# Protean
from protean.conf import active_config
from protean.core.exceptions import InvalidStateError, NotSupportedError, ObjectNotFoundError, ValidationError
from protean.core.field import Auto, Field, Reference, ValueObject
from protean.core.queryset import QuerySet
from protean.core.repository import repo_factory
from protean.utils import IdentityStrategy, inflection

# Local/Relative Imports
from ..core.field.association import _ReferenceField  # Relative path to private class

logger = logging.getLogger('protean.core.entity')


class _EntityMetaclass(type):
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
        parents = [b for b in bases if isinstance(b, _EntityMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base.Meta, 'abstract'):
                delattr(base.Meta, 'abstract')

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop('Meta', None)
        meta = attr_meta or getattr(new_class, 'Meta', None)
        setattr(new_class, 'meta_', EntityMeta(name, meta))

        # Load declared fields
        new_class._load_fields(attrs)

        # Load declared fields from Base class, in case this Entity is subclassing another
        new_class._load_base_class_fields(bases, attrs)

        # Lookup an already defined ID field or create an `Auto` field
        new_class._set_id_field()

        # Set up Relation Fields
        new_class._set_up_reference_fields()

        # Set up ValueObject Fields
        new_class._set_up_value_object_fields()

        # Load list of Attributes from declared fields, depending on type of fields
        new_class._load_attributes()

        return new_class

    @property
    def query(cls):
        """Construct an empty QuerySet associated with an Entity class
            everytime a new `query` object is created

        This is required so as not to corrupt the query object associated with the metaclass
        when invoked like `Dog.query.all()` directly. A new query, and a corresponding `ResultSet`
        would be created every time.
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

    def _set_up_value_object_fields(new_class):
        """Walk through value object fields and setup shadow attributes"""
        if new_class.meta_.declared_fields:
            for _, field in new_class.meta_.declared_fields.items():
                if isinstance(field, ValueObject):
                    shadow_fields = field.get_shadow_fields()
                    for shadow_field_name, shadow_field in shadow_fields:
                        setattr(new_class, shadow_field_name, shadow_field)

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
        for _, field_obj in new_class.meta_.declared_fields.items():
            if isinstance(field_obj, ValueObject):
                shadow_fields = field_obj.get_shadow_fields()
                for _, shadow_field in shadow_fields:
                    new_class.meta_.attributes[shadow_field.attribute_name] = shadow_field
            else:
                new_class.meta_.attributes[field_obj.get_attribute_name()] = field_obj


class EntityMeta:
    """ Metadata info for the entity.

    Options:
    - ``abstract``: Indicates that this is an abstract entity (Ignores all other meta options)
    - ``schema_name``: name of the schema (table/index/doc) used for persistence of this entity
        defaults to underscore version of the Entity name.
    - ``provider``: the name of the datasource associated with this
        entity, default value is `default`.
    - ``order_by``: default ordering of objects returned by filter queries.

    Also acts as a placeholder for generated entity fields like:

        :declared_fields: dict
            Any instances of `Field` included as attributes on either the class
            or on any of its superclasses will be include in this dictionary.
        :id_field: protean.core.Field
            An instance of the field that will serve as the unique identifier for the entity

    FIXME Make `EntityMeta` immutable
    """

    def __init__(self, entity_name, meta):
        self.abstract = getattr(meta, 'abstract', None) or False
        self.schema_name = (getattr(meta, 'schema_name', None) or
                            inflection.underscore(entity_name))
        self.provider = getattr(meta, 'provider', None) or 'default'

        # `order_by` can be provided either as a string or a tuple
        ordering = getattr(meta, 'order_by', ())
        if isinstance(ordering, str):
            self.order_by = ordering,
        else:
            self.order_by = tuple(ordering)

        # Initialize Options
        self.declared_fields = {}
        self.attributes = {}
        self.id_field = None

        # Domain Attributes
        self.aggregate = None
        self.bounded_context = None

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


class _FieldsCacheDescriptor:
    def __get__(self, instance, cls=None):
        if instance is None:
            return self
        res = instance.fields_cache = {}
        return res


class _EntityState:
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

    fields_cache = _FieldsCacheDescriptor()


class BaseEntity(metaclass=_EntityMetaclass):
    """The Base class for Protean-Compliant Domain Entities.

    Provides helper methods to custom define entity attributes, and query attribute names
    during runtime.

    Basic Usage::

        @Entity
        class Dog:
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

    (or)

        class Dog(BaseEntity):
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

        domain.register_element(Dog)

    During persistence, the model associated with this entity is retrieved dynamically from
            the repository factory. Model is usually initialized with a live DB connection.
    """

    class Meta:
        """Options object for an Entity.

        Check ``EntityMeta`` class for full documentation.
        """

    def __init__(self, *template, **kwargs):  # noqa: C901
        """
        Initialise the entity object.

        During initialization, set value on fields if vaidation passes.

        This initialization technique supports keyword arguments as well as dictionaries. You
            can even use a template for initial data.
        """

        if self.meta_.abstract is True:
            raise NotSupportedError(
                f'{self.__class__.__name__} class has been marked abstract'
                f' and cannot be instantiated')

        self.errors = {}

        # Set up the storage for instance state
        self.state_ = _EntityState()

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

        # Load Value Objects
        for field_name, field_obj in self.meta_.declared_fields.items():
            if isinstance(field_obj, (ValueObject)):
                attributes = [
                    (embedded_field.field_name, embedded_field.attribute_name)
                    for embedded_field
                    in field_obj.embedded_fields.values()
                    ]
                vals = {
                    name: getattr(self, attr)
                    for name, attr in attributes
                }
                value_object = field_obj.value_object_cls.build(**vals)
                setattr(self, field_name, value_object)
                loaded_fields.append(field_name)

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in self.meta_.declared_fields.items():
            if field_name not in loaded_fields:
                if not isinstance(field_obj, (Reference, _ReferenceField)):
                    setattr(self, field_name, None)

        # Raise any errors found during load
        if self.errors:
            raise ValidationError(self.errors)

    @classmethod
    def _generate_identity(cls):
        """Generate Unique Identifier, based on strategy"""
        if active_config.IDENTITY_STRATEGY == IdentityStrategy.UUID:
            return uuid4()

        return None  # Database will generate the identity

    @classmethod
    def build(cls, *template, **kwargs):
        """Factory method to initialize an Entity object"""
        instance = cls(*template, **kwargs)

        if not getattr(instance, cls.meta_.id_field.field_name, None):
            setattr(instance, cls.meta_.id_field.field_name, cls._generate_identity())

        return instance

    def __eq__(self, other):
        """Equaivalence check to be based only on Identity"""

        # FIXME Enhanced Equality Checks
        #   * Ensure IDs have values and both of them are not null
        #   * Ensure that the ID is of the right type
        #   * Ensure that Objects belong to the same `type`
        #   * Check Reference equality

        # FIXME Check if `==` and `in` operator work with __eq__

        if type(other) is type(self):
            self_id = getattr(self, self.meta_.id_field.field_name)
            other_id = getattr(other, other.meta_.id_field.field_name)

            return self_id == other_id

        return False

    def __hash__(self):
        """Overrides the default implementation and bases hashing on identity"""

        # FIXME Add Object Class Type to hash
        return hash(getattr(self, self.meta_.id_field.field_name))

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
        field_values = {}
        field_values = {
            field_name: getattr(self, field_name, None)
            for field_name, field_obj in self.meta_.declared_fields.items()
            if not isinstance(field_obj, ValueObject)
            }

        # FIXME Simplify fetching and appending Value Object dict values
        vo_fields = {
            field_name: getattr(self, field_name, None)
            for field_name, field_obj in self.meta_.declared_fields.items()
            if isinstance(field_obj, ValueObject)
            }

        vo_field_values = {}
        for vo_field_name, vo_field_obj in vo_fields.items():
            vo_field_values = {
                vo_field_name + '_' + field_name: getattr(vo_field_obj, field_name, None)
                for field_name, field_obj in vo_field_obj.meta_.declared_fields.items()
            }

        return {**field_values, **vo_field_values}

    def __repr__(self):
        """Friendly repr for Entity"""
        return '<%s: %s>' % (self.__class__.__name__, self)

    def __str__(self):
        identifier = getattr(self, self.meta_.id_field.field_name)
        return '%s object (%s)' % (
            self.__class__.__name__,
            '{}: {}'.format(self.meta_.id_field.field_name, identifier)
        )

    def clone(self):
        """Deepclone the entity, but reset state"""
        clone_copy = copy.deepcopy(self)
        clone_copy.state_ = _EntityState()

        return clone_copy

    ######################
    # Life-cycle methods #
    ######################

    @classmethod
    def get(cls, identifier: Any) -> 'BaseEntity':
        """Get a specific Record from the Repository

        :param identifier: id of the record to be fetched from the repository.
        """
        logger.debug(f'Lookup `{cls.__name__}` object with identifier {identifier}')
        # Get the ID field for the entity
        filters = {
            cls.meta_.id_field.field_name: identifier
        }

        # Find this item in the repository or raise Error
        results = cls.query.filter(**filters).limit(1).all()
        if not results:
            raise ObjectNotFoundError(
                f'`{cls.__name__}` object with identifier {identifier} '
                f'does not exist.')

        # Return the first result
        return results.first

    def reload(self) -> None:
        """Reload Entity from the repository"""
        if not self.state_.is_persisted or self.state_.is_changed:
            raise InvalidStateError(f'`{self.__class__.__name__}` object is in invalid state')

        # Retrieve the entity's ID by the configured Identifier field
        identifier = getattr(self, self.meta_.id_field.field_name)
        logger.debug(f'Lookup `{self.__class__.__name__}` object with '
                     f'identifier {self.meta_.id_field}')

        # Fetch the entity data from db by its identifier
        db_value = self.get(identifier)

        # Update own data from fetched entity data
        # This allows us to ``dog.reload()`` instead of ``dog = dog.reload()``
        self._update_data(db_value.to_dict())

    @classmethod
    def find_by(cls, **kwargs) -> 'BaseEntity':
        """Find a specific entity record that matches one or more criteria.

        :param kwargs: named arguments consisting of attr_name and attr_value pairs to search on
        """
        logger.debug(f'Lookup `{cls.__name__}` object with values '
                     f'{kwargs}')

        # Find this item in the repository or raise Error
        results = cls.query.filter(**kwargs).limit(1).all()

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
    def create(cls, *args, **kwargs) -> 'BaseEntity':
        """Create a new record in the repository.

        Also performs unique validations before creating the entity

        :param args: positional arguments for the entity
        :param kwargs: keyword arguments for the entity
        """
        logger.debug(
            f'Creating new `{cls.__name__}` object using data {kwargs}')

        model_cls = repo_factory.get_model(cls)
        repository = repo_factory.get_repository(cls)

        try:
            # Build the entity from the input arguments
            # Raises validation errors, if any, at this point
            entity = cls.build(*args, **kwargs)

            # Do unique checks, create this object and return it
            entity._validate_unique()

            # Perform Pre-Save Actions
            entity.pre_save()

            # Build the model object and create it
            model_obj = repository.create(model_cls.from_entity(entity))

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

            # Perform Post-Save Actions
            entity.post_save()

            return entity
        except ValidationError:
            # FIXME Log Exception
            raise

    def save(self):
        """Save a new Entity into repository.

        Performs unique validations before creating the entity.
        """
        logger.debug(
            f'Saving `{self.__class__.__name__}` object')

        # Fetch Model class and connected repository from Repository Factory
        model_cls = repo_factory.get_model(self.__class__)
        repository = repo_factory.get_repository(self.__class__)

        try:
            # If this is a new entity, generate ID
            if self.state_.is_new:
                if not getattr(self, self.meta_.id_field.field_name, None):
                    setattr(self, self.meta_.id_field.field_name, self.__class__._generate_identity())

            # Do unique checks, update the record and return the Entity
            self._validate_unique(create=False)

            # Perform Pre-Save Actions
            self.pre_save()

            # Build the model object and create it
            model_obj = repository.create(model_cls.from_entity(self))

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

            # Perform Post-Save Actions
            self.post_save()

            return self
        except Exception:
            # FIXME Log Exception
            raise

    def update(self, *data, **kwargs) -> 'BaseEntity':
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
        model_cls = repo_factory.get_model(self.__class__)
        repository = repo_factory.get_repository(self.__class__)

        try:
            # Update entity's data attributes
            self._update_data(*data, **kwargs)

            # Do unique checks, update the record and return the Entity
            self._validate_unique(create=False)

            # Perform Pre-Save Actions
            self.pre_save()

            repository.update(model_cls.from_entity(self))

            # Set Entity status to saved
            self.state_.mark_saved()

            # Perform Post-Save Actions
            self.post_save()

            return self
        except Exception:
            # FIXME Log Exception
            raise

    def _validate_unique(self, create=True):
        """ Validate the unique constraints for the entity """
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
                               entity_name=self.__class__.__name__,
                               field_name=filter_key)

    def delete(self):
        """Delete a Record from the Repository

        will perform callbacks and run validations before deletion.

        Throws ObjectNotFoundError if the object was not found in the repository.
        """
        # Fetch Model class and connected repository from Repository Factory
        model_cls = repo_factory.get_model(self.__class__)
        repository = repo_factory.get_repository(self.__class__)

        try:
            if not self.state_.is_destroyed:
                # Update entity's data attributes
                repository.delete(model_cls.from_entity(self))

                # Set Entity status to saved
                self.state_.mark_destroyed()

            return self
        except Exception:
            # FIXME Log Exception
            raise

    @classmethod
    def delete_all(cls):
        """Delete all Records in a Repository

        Will skip callbacks and validations.
        """
        # Fetch connected repository from Repository Factory
        repository = repo_factory.get_repository(cls)

        try:
            repository.delete_all()
        except Exception:
            # FIXME Log Exception
            raise

    def pre_save(self):
        """Pre-Save Hook"""
        pass

    def post_save(self):
        """Post-Save Hook"""
        pass
