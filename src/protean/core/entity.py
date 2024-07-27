"""Entity Functionality and Classes"""

import functools
import inspect
import json
import logging
from collections import defaultdict
from functools import partial

from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import Auto, HasMany, Reference, ValueObject
from protean.fields.association import Association
from protean.utils import (
    DomainObjects,
    derive_element_class,
    generate_identity,
    inflection,
)
from protean.utils.container import BaseContainer, IdentityMixin, OptionsMixin
from protean.utils.reflection import (
    _FIELDS,
    attributes,
    data_fields,
    declared_fields,
    fields,
    id_field,
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


class BaseEntity(OptionsMixin, IdentityMixin, BaseContainer):
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

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        # Record invariant methods
        setattr(subclass, "_invariants", defaultdict(dict))

    @classmethod
    def _default_options(cls):
        return [
            ("aggregate_cluster", None),
            ("auto_add_id_field", True),
            ("model", None),
            ("part_of", None),
            ("provider", "default"),
            ("schema_name", inflection.underscore(cls.__name__)),
        ]

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

        self._initialized = False

        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        self.errors = defaultdict(list)

        # Set up the storage for instance state
        self.state_ = _EntityState()

        # Placeholder for HasMany change tracking
        self._temp_cache = defaultdict(lambda: defaultdict(dict))

        # Attributes to preserve heirarchy of element instances
        self._owner = None
        self._root = None

        # To control invariant checks
        self._disable_invariant_checks = False

        # Placeholder for temporary storage of raised events
        self._events = []

        # Collect Reference field attribute names to prevent accidental overwriting
        # of shadow fields.
        reference_attributes = {
            field_obj.attribute_name: field_obj.field_name
            for field_obj in declared_fields(self).values()
            if isinstance(field_obj, Reference)
        }

        # Track fields that have been loaded
        loaded_fields = []

        # Pick identifier if provided in template or kwargs
        #   Generate if not provided
        #
        # Find identity field name
        id_field_obj = id_field(self)
        id_field_name = id_field_obj.field_name

        ############
        # ID Value #
        ############
        # Look for id field in kwargs and load value if present
        if kwargs and id_field_name in kwargs:
            setattr(self, id_field_name, kwargs.pop(id_field_name))
            loaded_fields.append(id_field_name)
        elif template:
            # Look for id field in template dictionary and load value if present
            for dictionary in template:
                if id_field_name in dictionary:
                    setattr(self, id_field_name, dictionary.pop(id_field_name))
                    loaded_fields.append(id_field_name)
                    break
        else:
            # A value was not supplied, so generate one
            if type(id_field_obj) is Auto and not id_field_obj.increment:
                setattr(
                    self,
                    id_field_name,
                    generate_identity(
                        id_field_obj.identity_strategy,
                        id_field_obj.identity_function,
                        id_field_obj.identity_type,
                    ),
                )
                loaded_fields.append(id_field_name)

        ########################
        # Load supplied values #
        ########################
        # Gather values from template
        template_values = {}
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f"Positional argument {dictionary} passed must be a dict. "
                    f"This argument serves as a template for loading common "
                    f"values.",
                )
            for field_name, val in dictionary.items():
                template_values[field_name] = val

        supplied_values = {**template_values, **kwargs}

        # Now load the attributes from template and kwargs
        for field_name, val in supplied_values.items():
            try:
                setattr(self, field_name, val)
            except ValidationError as err:
                for field_name in err.messages:
                    self.errors[field_name].extend(err.messages[field_name])
            finally:
                loaded_fields.append(field_name)

                # Also note reference field name if its attribute was loaded
                if field_name in reference_attributes:
                    loaded_fields.append(reference_attributes[field_name])

        ######################
        # Load value objects #
        ######################
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
                kwargs_values = {
                    name: supplied_values.get(attr) for name, attr in attrs
                }

                # Check if any of the values in `values` are not None
                #   If all values are None, it means that the value object is not being set
                #   and we should set it to None
                #
                #   If any of the values are not None, we should set the value object and its attributes
                #   to the values provided and let it trigger validations
                if any(kwargs_values.values()):
                    try:
                        value_object = field_obj.value_object_cls(**kwargs_values)
                        setattr(self, field_name, value_object)
                        loaded_fields.append(field_name)
                    except ValidationError as err:
                        for sub_field_name in err.messages:
                            self.errors[
                                "{}_{}".format(field_name, sub_field_name)
                            ].extend(err.messages[sub_field_name])

        #############################
        # Generate other identities #
        #############################
        # Load other identities
        for field_name, field_obj in declared_fields(self).items():
            if (
                field_name not in loaded_fields
                and type(field_obj) is Auto
                and not field_obj.increment
            ):
                setattr(
                    self,
                    field_obj.field_name,
                    generate_identity(
                        field_obj.identity_strategy,
                        field_obj.identity_function,
                        field_obj.identity_type,
                    ),
                )
                loaded_fields.append(field_obj.field_name)

        #####################
        # Load Associations #
        #####################
        for field_name, field_obj in declared_fields(self).items():
            if isinstance(field_obj, Association):
                getattr(self, field_name)  # This refreshes the values in associations

                # Set up add and remove methods. These are pseudo methods: `add_*`,
                #   `remove_*` and `filter_*` that point to the HasMany field's `add`,
                #   `remove` and `filter` methods. They are wrapped to ensure we pass
                #   the object that holds the values and temp_cache.
                if isinstance(field_obj, HasMany):
                    setattr(self, f"add_{field_name}", partial(field_obj.add, self))
                    setattr(
                        self, f"remove_{field_name}", partial(field_obj.remove, self)
                    )
                    setattr(
                        self, f"get_one_from_{field_name}", partial(field_obj.get, self)
                    )
                    setattr(
                        self, f"filter_{field_name}", partial(field_obj.filter, self)
                    )

        self.defaults()

        #################################
        # Mark remaining fields as None #
        #################################
        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in fields(self).items():
            if field_name not in loaded_fields and (
                not hasattr(self, field_name) or getattr(self, field_name) is None
            ):
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

        self._initialized = True

        # `_postcheck()` will return a `defaultdict(list)` if errors are to be raised
        custom_errors = self._postcheck(return_errors=True) or {}
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

    def _run_invariants(self, stage, return_errors=False):
        """Run invariants for a given stage."""
        if self._initialized and not self._disable_invariant_checks:
            errors = defaultdict(list)

            for invariant_method in self._invariants[stage].values():
                try:
                    invariant_method(self)
                except ValidationError as err:
                    for field_name in err.messages:
                        errors[field_name].extend(err.messages[field_name])

            # Run through all associations and trigger their invariants
            for field_name, field_obj in declared_fields(self).items():
                if isinstance(field_obj, (Association, ValueObject)):
                    value = getattr(self, field_name)
                    if value is not None:
                        items = value if isinstance(value, list) else [value]
                        for item in items:
                            # Pre-checks don't apply to ValueObjects, because VOs are immutable
                            #   and therefore cannot be changed once initialized.
                            if stage == "pre" and not isinstance(
                                field_obj, ValueObject
                            ):
                                item_errors = item._precheck(return_errors=True)
                            else:
                                item_errors = item._postcheck(return_errors=True)
                            if item_errors:
                                for sub_field_name, error_list in item_errors.items():
                                    errors[sub_field_name].extend(error_list)

            if return_errors:
                return errors

            if errors:
                raise ValidationError(errors)

    def _precheck(self, return_errors=False):
        """Invariant checks performed before entity changes"""
        return self._run_invariants("pre", return_errors=return_errors)

    def _postcheck(self, return_errors=False):
        """Invariant checks performed after initialization and attribute changes"""
        return self._run_invariants("post", return_errors=return_errors)

    def raise_(self, event) -> None:
        """Raise an event in the aggregate cluster.

        The event is always registered on the aggregate, irrespective of where
        it is raised in the entity cluster."""
        # Verify that event is indeed associated with this aggregate
        if event.meta_.part_of != self._root.__class__:
            raise ConfigurationError(
                f"Event `{event.__class__.__name__}` is not associated with"
                f" aggregate `{self._root.__class__.__name__}`"
            )

        identifier = getattr(self._root, id_field(self._root).field_name)

        # Set Fact Event stream to be `<aggregate_stream_name>-fact`
        if event.__class__.__name__.endswith("FactEvent"):
            stream = f"{self._root.meta_.stream_category}-fact-{identifier}"
        else:
            stream = f"{self._root.meta_.stream_category}-{identifier}"

        if self._root.meta_.is_event_sourced:
            # The version of the aggregate is incremented with every event raised, which is true
            # in the case of Event Sourced Aggregates.
            #
            # Except for Fact Events. Fact Events are raised after the aggregate has been persisted,
            if not event.__class__.__name__.endswith("FactEvent"):
                self._version += 1

            event_identity = f"{stream}-{self._version}"
            sequence_id = f"{self._version}"
        else:
            # Events are sometimes raised from within the aggregate, well-before persistence.
            #   In that case, the aggregate's next version has to be considered in events,
            #   because we want to associate the event with the version that will be persisted.
            #
            # Other times, an event is generated after persistence, like in the case of
            #   fact events. In this case, the aggregate's current version and next version
            #   will be the same.
            #
            # So we simply take the latest version, among `_version` and `_next_version`.
            aggregate_version = max(self._root._version, self._root._next_version)

            # This is just a counter to uniquely gather all events generated
            #   in the same edit session
            event_number = len(self._root._events) + 1

            event_identity = f"{stream}-{aggregate_version}.{event_number}"
            sequence_id = f"{aggregate_version}.{event_number}"

        # Event is immutable, so we clone a new event object from the event raised,
        # and add the enhanced metadata to it.
        event_with_metadata = event.__class__(
            event.to_dict(),
            _expected_version=self._root._event_position,
            _metadata={
                "id": event_identity,
                "type": event._metadata.type,
                "fqn": event._metadata.fqn,
                "kind": event._metadata.kind,
                "stream": stream,
                "origin_stream": event._metadata.origin_stream,
                "timestamp": event._metadata.timestamp,
                "version": event._metadata.version,
                "sequence_id": sequence_id,
                "payload_hash": hash(
                    json.dumps(
                        event.payload,
                        sort_keys=True,
                    )
                ),
            },
        )

        # Increment the event position after generating event
        self._root._event_position = self._root._event_position + 1

        self._root._events.append(event_with_metadata)

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
                    f"Positional argument {data} passed must be a dict. "
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

        for field_name, field_obj in data_fields(self).items():
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

    def _set_root_and_owner(self, root, owner):
        """Set the root and owner entities on all child entities

        This is a recursive process set in motion by the aggregate's `__init__` method.
        """
        self._root = root
        self._owner = owner

        # Set `_root` on all child entities
        for field_name, field_obj in declared_fields(self).items():
            # We care only about enclosed fields (associations)
            if isinstance(field_obj, Association):
                # Get current assigned value
                value = getattr(self, field_name)
                if value is not None:
                    # Link child entities to own root
                    items = value if isinstance(value, list) else [value]
                    for item in items:
                        if not item._root:
                            item._set_root_and_owner(self._root, self)


def entity_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseEntity, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Entity `{element_cls.__name__}` needs to be associated with an Aggregate"
        )

    # Set up reference fields
    if not element_cls.meta_.abstract:
        reference_field = None
        for field_obj in declared_fields(element_cls).values():
            if isinstance(field_obj, Reference):
                # An explicit `Reference` field is already present
                reference_field = field_obj
                break

        if reference_field is None:
            # If no explicit Reference field is present, create one
            reference_field = Reference(element_cls.meta_.part_of)

            # If part_of is a string, set field name to inflection.underscore(part_of)
            #   Else, if it is a class, extract class name and set field name to inflection.underscore(class_name)
            if isinstance(element_cls.meta_.part_of, str):
                field_name = inflection.underscore(element_cls.meta_.part_of)
            else:
                field_name = inflection.underscore(element_cls.meta_.part_of.__name__)

            setattr(element_cls, field_name, reference_field)

            # Set the name of the field on itself
            reference_field.__set_name__(element_cls, field_name)

            # FIXME Centralize this logic to add fields dynamically to _FIELDS
            field_objects = getattr(element_cls, _FIELDS)
            field_objects[field_name] = reference_field
            setattr(element_cls, _FIELDS, field_objects)

        # Set up shadow fields for Reference fields
        for _, field in fields(element_cls).items():
            if isinstance(field, Reference):
                shadow_field_name, shadow_field = field.get_shadow_field()
                shadow_field.__set_name__(element_cls, shadow_field_name)

    # Iterate through methods marked as `@invariant` and record them for later use
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_invariant"):
            element_cls._invariants[method._invariant][method_name] = method

    return element_cls


class invariant:
    @staticmethod
    def pre(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        setattr(wrapper, "_invariant", "pre")
        return wrapper

    @staticmethod
    def post(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        setattr(wrapper, "_invariant", "post")
        return wrapper
