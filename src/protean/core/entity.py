"""Entity Functionality and Classes"""
import copy
import logging

from collections import defaultdict
from functools import partial

from protean.container import BaseContainer, OptionsMixin
from protean.exceptions import IncorrectUsageError, NotSupportedError, ValidationError
from protean.fields import Auto, Field, HasMany, Reference, ValueObject
from protean.fields.association import Association
from protean.reflection import (
    _FIELDS,
    _ID_FIELD_NAME,
    attributes,
    declared_fields,
    fields,
    id_field,
)
from protean.utils import (
    DomainObjects,
    derive_element_class,
    generate_identity,
    inflection,
)

logger = logging.getLogger(__name__)


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


class BaseEntity(BaseContainer, OptionsMixin):
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

    class Meta:
        abstract = True

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        subclass.__set_id_field()
        subclass.__set_up_reference_fields()

    @classmethod
    def __set_id_field(new_class):
        """Lookup the id field for this entity and assign"""
        # FIXME What does it mean when there are no declared fields?
        #   Does it translate to an abstract entity?
        try:
            id_field = next(
                field
                for _, field in declared_fields(new_class).items()
                if isinstance(field, (Field, Reference)) and field.identifier
            )

            setattr(new_class, _ID_FIELD_NAME, id_field.field_name)

            # If the aggregate/entity has been marked abstract,
            #   and contains an identifier field, raise exception
            if new_class.meta_.abstract and id_field:
                raise IncorrectUsageError(
                    {
                        "_entity": [
                            f"Abstract Aggregate `{new_class.__name__}` marked as abstract cannot have"
                            " identity fields"
                        ]
                    }
                )
        except StopIteration:
            # If no id field is declared then create one
            #   If the aggregate/entity is marked abstract,
            #   avoid creating an identifier field.
            if not new_class.meta_.abstract:
                new_class.__create_id_field()

    @classmethod
    def __create_id_field(new_class):
        """Create and return a default ID field that is Auto generated"""
        id_field = Auto(identifier=True)

        setattr(new_class, "id", id_field)
        id_field.__set_name__(new_class, "id")

        setattr(new_class, _ID_FIELD_NAME, id_field.field_name)

        field_objects = getattr(new_class, _FIELDS)
        field_objects["id"] = id_field
        setattr(new_class, _FIELDS, field_objects)

    @classmethod
    def __set_up_reference_fields(subclass):
        """Walk through relation fields and setup shadow attributes"""
        for _, field in declared_fields(subclass).items():
            if isinstance(field, Reference):
                shadow_field_name, shadow_field = field.get_shadow_field()
                shadow_field.__set_name__(subclass, shadow_field_name)

    def __init__(self, *template, **kwargs):  # noqa: C901
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

        # Set up the storage for instance state
        self.state_ = _EntityState()

        # Placeholder for temporary association values
        self._temp_cache = defaultdict(lambda: defaultdict(dict))

        # Collect Reference field attribute names to prevent accidental overwriting
        # of shadow fields.
        reference_attributes = {
            field_obj.attribute_name: field_obj.field_name
            for field_obj in declared_fields(self).values()
            if isinstance(field_obj, Reference)
        }

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
            try:
                setattr(self, field_name, val)
            except ValidationError as err:
                for field_name in err.messages:
                    self.errors[field_name].extend(err.messages[field_name])
            else:
                loaded_fields.append(field_name)

                # Also note reference field name if its attribute was loaded
                if field_name in reference_attributes:
                    loaded_fields.append(reference_attributes[field_name])

        # Load Value Objects from associated fields
        #   This block will dynamically construct value objects from field values
        #   and associated the vo with the entity
        # If the value object was already provided, it will not be overridden.
        for field_name, field_obj in declared_fields(self).items():
            if isinstance(field_obj, (ValueObject)) and not getattr(self, field_name):
                attrs = [
                    (embedded_field.field_name, embedded_field.attribute_name)
                    for embedded_field in field_obj.embedded_fields.values()
                ]
                values = {name: kwargs.get(attr) for name, attr in attrs}
                try:
                    value_object = field_obj.value_object_cls(**values)
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
        for field_name, field_obj in declared_fields(self).items():
            if type(field_obj) is Auto and not field_obj.increment:
                if not getattr(self, field_obj.field_name, None):
                    setattr(self, field_obj.field_name, generate_identity())
                loaded_fields.append(field_obj.field_name)

        # Load Associations
        for field_name, field_obj in declared_fields(self).items():
            if isinstance(field_obj, Association):
                getattr(self, field_name)  # This refreshes the values in associations

                # Set up add and remove methods. These are pseudo methods, `add_*` and
                #   `remove_*` that point to the HasMany field's `add` and `remove`
                #   methods. They are wrapped to ensure we pass the object that holds
                #   the values and temp_cache.
                if isinstance(field_obj, HasMany):
                    setattr(self, f"add_{field_name}", partial(field_obj.add, self))
                    setattr(
                        self, f"remove_{field_name}", partial(field_obj.remove, self)
                    )
                    setattr(
                        self,
                        f"_mark_changed_{field_name}",
                        partial(field_obj._mark_changed, self),
                    )

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in fields(self).items():
            if field_name not in loaded_fields:
                if not isinstance(field_obj, Association):
                    try:
                        setattr(self, field_name, None)

                        # If field is a VO, set underlying attributes to None as well
                        if isinstance(field_obj, ValueObject):
                            for embedded_field in field_obj.embedded_fields.values():
                                setattr(self, embedded_field.attribute_name, None)
                    except ValidationError as err:
                        for field_name in err.messages:
                            self.errors[field_name].extend(err.messages[field_name])

        for field_name, field_obj in attributes(self).items():
            if field_name not in loaded_fields and not hasattr(self, field_name):
                setattr(self, field_name, None)

        self.defaults()

        # `clean()` will return a `defaultdict(list)` if errors are to be raised
        custom_errors = self.clean() or {}
        for field in custom_errors:
            self.errors[field].extend(custom_errors[field])

        # Raise any errors found during load
        if self.errors:
            logger.error(f"Error during initialization: {dict(self.errors)}")
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

    def __eq__(self, other):
        """Equivalence check to be based only on Identity"""

        # FIXME Enhanced Equality Checks
        #   * Ensure IDs have values and both of them are not null
        #   * Ensure that the ID is of the right type
        #   * Ensure that Objects belong to the same `type`
        #   * Check Reference equality

        # FIXME Check if `==` and `in` operator work with __eq__

        if type(other) is type(self):
            self_id = getattr(self, id_field(self).field_name)
            other_id = getattr(other, id_field(other).field_name)

            return self_id == other_id

        return False

    def __hash__(self):
        """Overrides the default implementation and bases hashing on identity"""

        # FIXME Add Object Class Type to hash
        return hash(getattr(self, id_field(self).field_name))

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
            logger.error(f"Errors on Update: {dict(self.errors)}")
            raise ValidationError(self.errors)

    def to_dict(self):
        """Return entity data as a dictionary"""
        # FIXME Memoize this function
        field_values = {}

        for field_name, field_obj in declared_fields(self).items():
            if (
                not isinstance(field_obj, (ValueObject, Reference))
                and getattr(self, field_name, None) is not None
            ):
                field_values[field_name] = field_obj.as_dict(
                    getattr(self, field_name, None)
                )
            elif isinstance(field_obj, ValueObject):
                value = field_obj.as_dict(getattr(self, field_name, None))
                if value:
                    field_values[field_name] = field_obj.as_dict(
                        getattr(self, field_name, None)
                    )

        return field_values

    def __repr__(self):
        """Friendly repr for Entity"""
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self):
        identifier = getattr(self, id_field(self).field_name)
        return "%s object (%s)" % (
            self.__class__.__name__,
            "{}: {}".format(id_field(self).field_name, identifier),
        )

    def clone(self):
        """Deepclone the entity, but reset state"""
        clone_copy = copy.deepcopy(self)
        clone_copy.state_ = _EntityState()

        return clone_copy

    @classmethod
    def _default_options(cls):
        return [
            ("provider", "default"),
            ("model", None),
            ("aggregate_cls", None),
            ("schema_name", inflection.underscore(cls.__name__)),
        ]

    @classmethod
    def _extract_options(cls, **opts):
        """A stand-in method for setting customized options on the Domain Element

        Empty by default. To be overridden in each Element that expects or needs
        specific options.
        """
        for key, default in cls._default_options():
            value = (
                opts.pop(key, None)
                or (hasattr(cls.meta_, key) and getattr(cls.meta_, key))
                or default
            )
            setattr(cls.meta_, key, value)


def entity_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseEntity, **kwargs)

    if element_cls.meta_.abstract is True:
        raise NotSupportedError(
            {
                "_entity": [
                    f"`{element_cls.__name__}` class has been marked abstract"
                    f" and cannot be instantiated"
                ]
            }
        )

    if not element_cls.meta_.aggregate_cls:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Entity `{element_cls.__name__}` needs to be associated with an Aggregate"
                ]
            }
        )

    return element_cls
