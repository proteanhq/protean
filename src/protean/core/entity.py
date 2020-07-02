"""Entity Functionality and Classes"""
# Standard Library Imports
import copy
import logging

from collections import defaultdict
from uuid import uuid4

# Protean
from protean.core.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.core.field.association import Association, Reference
from protean.core.field.basic import Auto, Field
from protean.core.field.embedded import ValueObjectField
from protean.domain import DomainObjects
from protean.globals import current_domain
from protean.utils import IdentityStrategy, IdentityType, inflection

# Local/Relative Imports
from ..core.field.association import _ReferenceField  # Relative path to private class

logger = logging.getLogger("protean.domain.entity")


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

        # Remove `abstract` if defined in base classes
        for base in bases:
            if hasattr(base, "Meta") and hasattr(base.Meta, "abstract"):
                delattr(base.Meta, "abstract")

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop(
            "Meta", None
        )  # Gather Metadata defined in inner `Meta` class
        entity_meta = EntityMeta(name, attr_meta)  # Initialize the Metadata container
        setattr(
            new_class, "meta_", entity_meta
        )  # Associate the Metadata container with new class

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

        return new_class

    def _load_base_class_fields(new_class, bases, attrs):
        """If this class is subclassing another Entity, add that Entity's
        fields.  Note that we loop over the bases in *reverse*.
        This is necessary in order to maintain the correct order of fields.
        """
        for base in reversed(bases):
            if hasattr(base, "meta_") and hasattr(base.meta_, "declared_fields"):
                base_class_fields = {
                    field_name: field_obj
                    for (field_name, field_obj) in base.meta_.declared_fields.items()
                    if (
                        field_name not in attrs
                        and not isinstance(field_obj, Association)
                        and not field_obj.identifier
                    )
                }
                new_class._load_fields(base_class_fields)

    def _load_fields(new_class, attrs):
        """Load field items into Class.

        This method sets up the primary attribute of an association.
        If Child class has defined an attribute so `parent = field.Reference(Parent)`, then `parent`
        is set up in this method, while `parent_id` is set up in `_set_up_reference_fields()`.
        """
        for attr_name, attr_obj in attrs.items():
            if isinstance(attr_obj, (Association, Field, Reference)):
                setattr(new_class, attr_name, attr_obj)
                new_class.meta_.declared_fields[attr_name] = attr_obj

    def _set_up_reference_fields(new_class):
        """Walk through relation fields and setup shadow attributes"""
        if new_class.meta_.declared_fields:
            for _, field in new_class.meta_.declared_fields.items():
                if isinstance(field, Reference):
                    shadow_field_name, shadow_field = field.get_shadow_field()
                    new_class.meta_.reference_fields[shadow_field_name] = shadow_field
                    shadow_field.__set_name__(new_class, shadow_field_name)

    def _set_up_value_object_fields(new_class):
        """Walk through value object fields and setup shadow attributes"""
        if new_class.meta_.declared_fields:
            for _, field in new_class.meta_.declared_fields.items():
                if isinstance(field, ValueObjectField):
                    shadow_fields = field.get_shadow_fields()
                    for shadow_field_name, shadow_field in shadow_fields:
                        new_class.meta_.value_object_fields[
                            shadow_field_name
                        ] = shadow_field

    def _set_id_field(new_class):
        """Lookup the id field for this entity and assign"""
        # FIXME What does it mean when there are no declared fields?
        #   Does it translate to an abstract entity?
        if new_class.meta_.declared_fields:
            try:
                new_class.meta_.id_field = next(
                    field
                    for _, field in new_class.meta_.declared_fields.items()
                    if isinstance(field, (Field, Reference)) and field.identifier
                )
            except StopIteration:
                # If no id field is declared then create one
                new_class._create_id_field()

    def _create_id_field(new_class):
        """Create and return a default ID field that is Auto generated"""
        id_field = Auto(identifier=True)

        setattr(new_class, "id", id_field)
        id_field.__set_name__(new_class, "id")

        # Ensure ID field is updated properly in Meta attribute
        new_class.meta_.declared_fields["id"] = id_field
        new_class.meta_.id_field = id_field


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
        self.abstract = getattr(meta, "abstract", None) or False
        self.schema_name = getattr(meta, "schema_name", None) or inflection.underscore(
            entity_name
        )
        self.provider = getattr(meta, "provider", None) or "default"
        self.model = getattr(meta, "model", None)

        # `order_by` can be provided either as a string or a tuple
        ordering = getattr(meta, "order_by", ())
        if isinstance(ordering, str):
            self.order_by = (ordering,)
        else:
            self.order_by = tuple(ordering)

        # Initialize Options
        self.declared_fields = {}
        self.value_object_fields = {}
        self.reference_fields = {}
        self.id_field = None

        # Domain Attributes
        self.aggregate_cls = getattr(meta, "aggregate_cls", None)
        self.bounded_context = getattr(meta, "bounded_context", None)

    @property
    def mandatory_fields(self):
        """ Return the mandatory fields for this entity """
        return {
            field_name: field_obj
            for field_name, field_obj in self.attributes.items()
            if not isinstance(field_obj, Association) and field_obj.required
        }

    @property
    def unique_fields(self):
        """ Return the unique fields for this entity """
        return {
            field_name: field_obj
            for field_name, field_obj in self.attributes.items()
            if not isinstance(field_obj, Association) and field_obj.unique
        }

    @property
    def auto_fields(self):
        return {
            field_name: field_obj
            for field_name, field_obj in self.declared_fields.items()
            if isinstance(field_obj, Auto)
        }

    @property
    def attributes(self):
        attributes_dict = {}
        for _, field_obj in self.declared_fields.items():
            if isinstance(field_obj, ValueObjectField):
                shadow_fields = field_obj.get_shadow_fields()
                for _, shadow_field in shadow_fields:
                    attributes_dict[shadow_field.attribute_name] = shadow_field
            elif isinstance(field_obj, Reference):
                attributes_dict[field_obj.get_attribute_name()] = field_obj.relation
            elif isinstance(field_obj, Field):
                attributes_dict[field_obj.get_attribute_name()] = field_obj
            else:  # This field is an association. Ignore recording it as an attribute
                pass

        return attributes_dict


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

    def mark_new(self):
        self._new = True

    def mark_saved(self):
        self._new = False
        self._changed = False

    mark_retrieved = (
        mark_saved  # Alias as placeholder so that future change wont affect interface
    )

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

    You can define an Entity with the help of `entity` annotation::

        @domain.entity
        class User:
            id = field.Integer(identifier=True)
            first_name = field.String(required=True, max_length=50)
            last_name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)

    (or)

    Or, you can directly subclass from `BaseEntity`::

        class User(BaseEntity):
            id = field.Integer(identifier=True)
            first_name = field.String(required=True, max_length=50)
            last_name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)

        domain.register_element(User)

    During persistence, the model associated with this entity is retrieved dynamically from the repository factory,
    initialized with a live connection to the datastore.
    """

    element_type = DomainObjects.ENTITY

    def __init__(self, *template, raise_errors=True, **kwargs):  # noqa: C901
        """
        Initialise the entity object.

        During initialization, set value on fields if validation passes.

        This initialization technique supports keyword arguments as well as dictionaries. The objects initialized
        in the following example have the same structure::

            user1 = User({'first_name': 'John', 'last_name': 'Doe'})

            user2 = User(first_name='John', last_name='Doe')

        You can also specify a template for initial data and override specific attributes::

            base_user = User({'age': 15})

            user = User(base_user.to_dict(), first_name='John', last_name='Doe')
        """

        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        self.errors = defaultdict(list)
        self.raise_errors = raise_errors

        # Set up the storage for instance state
        self.state_ = _EntityState()

        # Load the attributes based on the template
        loaded_fields = []
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f'Positional argument "{dictionary}" passed must be a dict.'
                    f"This argument serves as a template for loading common "
                    f"values.",
                )
            for field_name, val in dictionary.items():
                if field_name not in kwargs:
                    kwargs[field_name] = val

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            loaded_fields.append(field_name)
            try:
                setattr(self, field_name, val)
            except ValidationError as err:
                for field_name in err.messages:
                    self.errors[field_name].extend(err.messages[field_name])

        # Load Value Objects from associated fields
        #   This block will dynamically construct value objects from field values
        #   and associated the vo with the entity
        # If the value object was already provided, it will not be overridden.
        for field_name, field_obj in self.meta_.declared_fields.items():
            if isinstance(field_obj, (ValueObjectField)) and not getattr(
                self, field_name
            ):
                attributes = [
                    (embedded_field.field_name, embedded_field.attribute_name)
                    for embedded_field in field_obj.embedded_fields.values()
                ]
                values = {name: kwargs.get(attr) for name, attr in attributes}
                try:
                    value_object = field_obj.value_object_cls.build(**values)
                    # Set VO value only if the value object is not None/Empty
                    if value_object:
                        setattr(self, field_name, value_object)
                        loaded_fields.append(field_name)
                except ValidationError as err:
                    for sub_field_name in err.messages:
                        self.errors["{}_{}".format(field_name, sub_field_name)].extend(
                            err.messages[sub_field_name]
                        )

        # Load Identities
        if (
            not getattr(self, self.meta_.id_field.field_name, None)
            and type(self.meta_.id_field) is Auto
        ):
            setattr(self, self.meta_.id_field.field_name, self.generate_identity())
            loaded_fields.append(self.meta_.id_field.field_name)

        # Load Associations
        for field_name, field_obj in self.meta_.declared_fields.items():
            if isinstance(field_obj, Association):
                getattr(self, field_name)  # This refreshes the values in associations

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in self.meta_.declared_fields.items():
            if field_name not in loaded_fields:
                if not isinstance(field_obj, (Reference, _ReferenceField, Association)):
                    try:
                        setattr(self, field_name, None)

                        # If field is a VO, set underlying attributes to None as well
                        if isinstance(field_obj, ValueObjectField):
                            for embedded_field in field_obj.embedded_fields.values():
                                setattr(self, embedded_field.attribute_name, None)
                    except ValidationError as err:
                        for field_name in err.messages:
                            self.errors[field_name].extend(err.messages[field_name])

        for field_name, field_obj in self.meta_.attributes.items():
            if field_name not in loaded_fields and not hasattr(self, field_name):
                setattr(self, field_name, None)

        self.defaults()

        # `clean()` will return a `defaultdict(list)` if errors are to be raised
        custom_errors = self.clean() or {}
        for field in custom_errors:
            self.errors[field].extend(custom_errors[field])

        # Raise any errors found during load
        if self.errors and self.raise_errors:
            logger.error(self.errors)
            raise ValidationError(self.errors)

    def defaults(self):
        """Placeholder method for defaults.
        To be overridden in concrete Containers, when an attribute's default depends on other attribute values.
        """

    def clean(self):
        """Placeholder method for validations.
        To be overridden in concrete Containers, when complex validations spanning multiple fields are required.
        """
        return defaultdict(list)

    @classmethod
    def generate_identity(cls):
        """Generate Unique Identifier, based on configured strategy"""
        if current_domain.config["IDENTITY_STRATEGY"] == IdentityStrategy.UUID:
            if current_domain.config["IDENTITY_TYPE"] == IdentityType.INTEGER:
                return uuid4().int
            elif current_domain.config["IDENTITY_TYPE"] == IdentityType.STRING:
                return str(uuid4())
            elif current_domain.config["IDENTITY_TYPE"] == IdentityType.UUID:
                return uuid4()
            else:
                raise ConfigurationError(
                    f'Unknown Identity Type {current_domain.config["IDENTITY_TYPE"]}'
                )

        return None  # Database will generate the identity

    def __eq__(self, other):
        """Equivalence check to be based only on Identity"""

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
                    f"This argument serves as a template for loading common "
                    f"values.",
                )
            for field_name, val in data.items():
                setattr(self, field_name, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            setattr(self, field_name, val)

        # Raise any errors found during update
        if self.errors:
            logger.error(self.errors)
            raise ValidationError(self.errors)

    def to_dict(self):
        """ Return entity data as a dictionary """
        field_values = {}
        field_values = {
            field_name: getattr(self, field_name, None)
            for field_name, field_obj in self.meta_.declared_fields.items()
            if not isinstance(field_obj, ValueObjectField)
        }

        # FIXME Simplify fetching and appending Value Object dict values
        vo_fields = {
            field_name: getattr(self, field_name, None)
            for field_name, field_obj in self.meta_.declared_fields.items()
            if isinstance(field_obj, ValueObjectField)
        }

        vo_field_values = {}
        for vo_field_name, vo_field_obj in vo_fields.items():
            if vo_field_obj:
                vo_field_values.update(
                    {
                        vo_field_name
                        + "_"
                        + field_name: getattr(vo_field_obj, field_name, None)
                        for field_name, field_obj in vo_field_obj.meta_.declared_fields.items()
                    }
                )

        return {**field_values, **vo_field_values}

    def __repr__(self):
        """Friendly repr for Entity"""
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self):
        identifier = getattr(self, self.meta_.id_field.field_name)
        return "%s object (%s)" % (
            self.__class__.__name__,
            "{}: {}".format(self.meta_.id_field.field_name, identifier),
        )

    def clone(self):
        """Deepclone the entity, but reset state"""
        clone_copy = copy.deepcopy(self)
        clone_copy.state_ = _EntityState()

        return clone_copy


class EntityFactory:
    @classmethod
    def prep_class(cls, element_cls, **kwargs):
        if issubclass(element_cls, BaseEntity):
            new_element_cls = element_cls
        else:
            try:
                new_dict = element_cls.__dict__.copy()
                new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

                new_element_cls = type(element_cls.__name__, (BaseEntity,), new_dict)
            except BaseException as exc:
                logger.debug("Error during Element registration:", repr(exc))
                raise IncorrectUsageError(
                    "Invalid class {element_cls.__name__} for type {element_type.value}"
                    " (Error: {exc})",
                )

        cls._validate_entity_class(new_element_cls)

        new_element_cls.meta_.provider = (
            kwargs.pop("provider", None)
            or (hasattr(new_element_cls, "meta_") and new_element_cls.meta_.provider)
            or "default"
        )
        new_element_cls.meta_.model = (
            kwargs.pop("model", None)
            or (hasattr(new_element_cls, "meta_") and new_element_cls.meta_.model)
            or None
        )
        new_element_cls.meta_.bounded_context = kwargs.pop("bounded_context", None) or (
            hasattr(new_element_cls, "meta_") and new_element_cls.meta_.bounded_context
        )
        new_element_cls.meta_.aggregate_cls = (
            kwargs.pop("aggregate_cls", None)
            or (
                hasattr(new_element_cls, "meta_")
                and new_element_cls.meta_.aggregate_cls
            )
            or None
        )

        if not new_element_cls.meta_.aggregate_cls:
            raise IncorrectUsageError(
                f"Entity `{new_element_cls.__name__}` needs to be associated with an Aggregate"
            )

        return new_element_cls

    @classmethod
    def _validate_entity_class(cls, element_cls):
        if not issubclass(element_cls, BaseEntity):
            raise AssertionError(
                f"Element {element_cls.__name__} must be subclass of `BaseEntity`"
            )

        if element_cls.meta_.abstract is True:
            raise NotSupportedError(
                f"{element_cls.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        return True
