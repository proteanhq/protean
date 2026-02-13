"""Entity Functionality and Classes"""

from __future__ import annotations

import functools
import inspect
import logging
from collections import defaultdict
from functools import partial
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, PrivateAttr
from pydantic import ValidationError as PydanticValidationError

from protean.core.value_object import _PydanticFieldShim
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import Auto, HasMany, HasOne, Reference, ValueObject
from protean.fields.association import Association, _ReferenceField
from protean.fields.embedded import _ShadowField
from protean.utils import (
    DomainObjects,
    Processing,
    derive_element_class,
    generate_identity,
    inflection,
)
from protean.utils.container import BaseContainer, IdentityMixin, OptionsMixin
from protean.utils.eventing import DomainMeta, Metadata, MessageHeaders, MessageEnvelope
from protean.utils.globals import current_domain
from protean.utils.reflection import (
    _FIELDS,
    _ID_FIELD_NAME,
    association_fields,
    reference_fields,
    data_fields,
    declared_fields,
    fields,
    id_field,
    value_object_fields,
)

logger = logging.getLogger(__name__)

# Descriptor types that should bypass Pydantic's __setattr__ and be routed
# through the Python descriptor protocol via object.__setattr__().
_DESCRIPTOR_TYPES = (Association, Reference, ValueObject, _ReferenceField, _ShadowField)


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


class _LegacyBaseEntity(OptionsMixin, IdentityMixin, BaseContainer):
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
            ("database_model", None),
            ("part_of", None),
            ("provider", "default"),
            ("schema_name", inflection.underscore(cls.__name__)),
            ("limit", 100),
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

        # Walk through reference fields and set attributes to None, if the
        #   field was not specified explicitly.
        for field_obj in reference_fields(self).values():
            attr_name = field_obj.attribute_name
            if (
                # Field is not loaded yet
                attr_name not in loaded_fields
                # Field was not specified explicitly
                and not hasattr(self, attr_name)
            ):
                setattr(self, attr_name, None)

        # Walk through value objects and set their shadow attributes to None, if the
        #   value object was not specified explicitly.
        for field_obj in value_object_fields(self).values():
            shadow_fields = field_obj.get_shadow_fields()
            for _, shadow_field in shadow_fields:
                attr_name = shadow_field.attribute_name
                if (
                    # Field is not loaded yet
                    attr_name not in loaded_fields
                    # Field was not specified explicitly
                    and not hasattr(self, attr_name)
                ):
                    setattr(self, attr_name, None)

        # Only run invariant checks if there are no field validation errors
        if not self.errors:
            # `_postcheck()` will return a `defaultdict(list)` if errors are to be raised
            custom_errors = self._postcheck(return_errors=True) or {}
            for field in custom_errors:
                self.errors[field].extend(custom_errors[field])

        # Raise any errors found during load
        if self.errors:
            logger.error(f"Error during initialization: {dict(self.errors)}")
            raise ValidationError(self.errors)

        self._initialized = True

    def defaults(self):
        """Placeholder method for defaults.
        To be overridden in concrete Containers, when an attribute's default depends on other attribute values.
        """

    def _run_invariants(self, stage, return_errors=False):
        """Run invariants for a given stage."""
        if not self._disable_invariant_checks:
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
                                item_errors = item._postcheck()
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

        headers = MessageHeaders(
            id=event_identity,
            type=event.__class__.__type__,
            stream=stream,
            time=event._metadata.headers.time
            if (event._metadata.headers and event._metadata.headers.time)
            else None,
        )

        # Build envelope with checksum
        envelope = MessageEnvelope.build(event.payload)

        # Build domain metadata
        domain_meta = DomainMeta(
            event._metadata.domain.to_dict(),
            # FIXME Should Fact Events be a different category?
            stream_category=self._root.meta_.stream_category,
            sequence_id=sequence_id,
            asynchronous=current_domain.config["event_processing"]
            == Processing.ASYNC.value,
        )

        metadata = Metadata(
            headers=headers,
            envelope=envelope,
            domain=domain_meta,
        )

        event_with_metadata = event.__class__(
            event.payload,
            _expected_version=self._root._event_position,
            _metadata=metadata,
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


# ---------------------------------------------------------------------------
# New Pydantic-based BaseEntity
# ---------------------------------------------------------------------------
class BaseEntity(BaseModel, OptionsMixin):
    """Pydantic-based base class for Entity domain elements.

    Mutable, identity-based equality, with invariant checking.
    Uses Pydantic v2 BaseModel with ``validate_assignment=True`` for field
    declaration, validation, and mutation.

    Fields are declared using standard Python type annotations with optional
    ``pydantic.Field`` constraints.  Identity fields must be annotated with
    ``json_schema_extra={"identifier": True}``.
    """

    element_type: ClassVar[str] = DomainObjects.ENTITY

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        ignored_types=(HasOne, HasMany, Reference, ValueObject),
    )

    # Internal state (PrivateAttr — excluded from model_dump/schema)
    _initialized: bool = PrivateAttr(default=False)
    _state: _EntityState = PrivateAttr(default_factory=_EntityState)
    _root: Any = PrivateAttr(default=None)
    _owner: Any = PrivateAttr(default=None)
    _temp_cache: Any = PrivateAttr(
        default_factory=lambda: defaultdict(lambda: defaultdict(dict))
    )
    _events: list = PrivateAttr(default_factory=list)
    _disable_invariant_checks: bool = PrivateAttr(default=False)

    def __new__(cls, *args: Any, **kwargs: Any) -> BaseEntity:
        if cls is BaseEntity:
            raise NotSupportedError("BaseEntity cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [
            ("aggregate_cluster", None),
            ("auto_add_id_field", True),
            ("database_model", None),
            ("part_of", None),
            ("provider", "default"),
            ("schema_name", inflection.underscore(cls.__name__)),
            ("limit", 100),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Initialize invariant storage
        setattr(cls, "_invariants", defaultdict(dict))
        # Set empty __container_fields__ as placeholder (populated later by __pydantic_init_subclass__)
        setattr(cls, _FIELDS, {})

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Called by Pydantic AFTER model_fields are fully populated."""
        super().__pydantic_init_subclass__(**kwargs)

        # Build __container_fields__ bridge from Pydantic model_fields
        fields_dict: dict[str, _PydanticFieldShim] = {}
        for fname, finfo in cls.model_fields.items():
            fields_dict[fname] = _PydanticFieldShim(fname, finfo, finfo.annotation)

        # Add association and VO descriptors from the full MRO
        for klass in cls.__mro__:
            for name, attr in vars(klass).items():
                if (
                    isinstance(attr, (Association, Reference, ValueObject))
                    and name not in fields_dict
                ):
                    fields_dict[name] = attr

        setattr(cls, _FIELDS, fields_dict)

        # Track identity field
        if not cls.meta_.abstract:
            cls.__track_id_field()

    @classmethod
    def __track_id_field(cls) -> None:
        """Find the field marked ``identifier=True`` and record its name."""
        try:
            id_fld = next(
                field
                for _, field in getattr(cls, _FIELDS, {}).items()
                if getattr(field, "identifier", False)
            )
            setattr(cls, _ID_FIELD_NAME, id_fld.field_name)
        except StopIteration:
            pass

    @staticmethod
    def _get_class_descriptor(cls: type, name: str) -> Any:
        """Look up a descriptor on the class MRO without triggering __get__.

        ``getattr(cls, name)`` invokes the data descriptor protocol, which
        may return ``None`` or ``[]`` for association descriptors.  Scanning
        ``__dict__`` directly returns the raw descriptor object.
        """
        for klass in cls.__mro__:
            if name in vars(klass):
                attr = vars(klass)[name]
                if isinstance(attr, _DESCRIPTOR_TYPES):
                    return attr
        return None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Pop internal kwargs that should not reach Pydantic
        owner = kwargs.pop("_owner", None)
        root = kwargs.pop("_root", None)

        # Pop association/VO descriptor kwargs and shadow field kwargs before
        # Pydantic init.  Shadow fields (e.g. order_id, billing_address_street)
        # are set dynamically during domain resolution and must not be passed
        # to Pydantic's __init__ which rejects them with extra="forbid".
        descriptor_kwargs: dict[str, Any] = {}
        shadow_kwargs: dict[str, Any] = {}

        # Build the set of known shadow field names from descriptors in
        # __container_fields__.  This prevents silently swallowing truly
        # unknown kwargs that Pydantic should reject.
        _shadow_field_names: set[str] = set()
        for _, fobj in getattr(type(self), _FIELDS, {}).items():
            if isinstance(fobj, Reference):
                attr_name = fobj.get_attribute_name()
                if attr_name:
                    _shadow_field_names.add(attr_name)
            elif isinstance(fobj, ValueObject):
                for sf in fobj.embedded_fields.values():
                    _shadow_field_names.add(sf.attribute_name)

        for name in list(kwargs):
            if self._get_class_descriptor(type(self), name) is not None:
                descriptor_kwargs[name] = kwargs.pop(name)
            elif name in _shadow_field_names:
                shadow_kwargs[name] = kwargs.pop(name)

        # Support template dict pattern: Entity({"key": "val"}, key2="val2")
        if args:
            for template in args:
                if not isinstance(template, dict):
                    raise AssertionError(
                        f"Positional argument {template} passed must be a dict. "
                        f"This argument serves as a template for loading common "
                        f"values.",
                    )
                # Also separate descriptor and shadow kwargs from template dicts
                for tname in list(template):
                    if self._get_class_descriptor(type(self), tname) is not None:
                        descriptor_kwargs[tname] = template.pop(tname)
                    elif tname in _shadow_field_names:
                        shadow_kwargs[tname] = template.pop(tname)
                kwargs.update(template)

        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            from protean.core.value_object import _convert_pydantic_errors

            raise ValidationError(_convert_pydantic_errors(e))

        # Set hierarchy references
        if owner is not None:
            self._owner = owner
        if root is not None:
            self._root = root

        # Restore shadow field values directly into __dict__ (they bypass Pydantic)
        for name, value in shadow_kwargs.items():
            self.__dict__[name] = value

        # Reconstruct ValueObjects from shadow kwargs when the VO itself
        # wasn't explicitly provided (e.g. during repository retrieval).
        for field_name, field_obj in value_object_fields(self).items():
            if field_name not in descriptor_kwargs and not getattr(
                self, field_name, None
            ):
                # Gather shadow field values from shadow_kwargs
                vo_kwargs = {}
                for embedded_field in field_obj.embedded_fields.values():
                    vo_kwargs[embedded_field.field_name] = shadow_kwargs.get(
                        embedded_field.attribute_name
                    )
                # Only reconstruct if at least one value is not None
                if any(v is not None for v in vo_kwargs.values()):
                    descriptor_kwargs[field_name] = field_obj.value_object_cls(
                        **vo_kwargs
                    )

        # Set association/VO values via descriptors (triggers __set__)
        for name, value in descriptor_kwargs.items():
            setattr(self, name, value)

    def model_post_init(self, __context: Any) -> None:
        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        # Discover invariants from MRO
        self._discover_invariants()

        self.defaults()

        # Initialize VO shadow fields to None when the VO itself is not set
        for field_obj in value_object_fields(self).values():
            for _, shadow_field in field_obj.get_shadow_fields():
                attr_name = shadow_field.attribute_name
                if attr_name not in self.__dict__:
                    self.__dict__[attr_name] = None

        # Initialize Reference shadow fields to None when not already set
        for field_obj in reference_fields(self).values():
            shadow_name, shadow = field_obj.get_shadow_field()
            if shadow_name not in self.__dict__:
                self.__dict__[shadow_name] = None

        # Setup association pseudo-methods (add_*, remove_*, get_one_from_*, filter_*)
        for field_name, field_obj in association_fields(self).items():
            getattr(self, field_name)  # Initialize/refresh associations

            if isinstance(field_obj, HasMany):
                setattr(self, f"add_{field_name}", partial(field_obj.add, self))
                setattr(self, f"remove_{field_name}", partial(field_obj.remove, self))
                setattr(
                    self, f"get_one_from_{field_name}", partial(field_obj.get, self)
                )
                setattr(self, f"filter_{field_name}", partial(field_obj.filter, self))

        # Run post-invariants after init
        errors = self._run_invariants("post", return_errors=True) or {}
        if errors:
            raise ValidationError(errors)

        self._initialized = True

    def _discover_invariants(self) -> None:
        """Scan class MRO for @invariant decorated methods and register them."""
        for klass in type(self).__mro__:
            for name, attr in vars(klass).items():
                if callable(attr) and hasattr(attr, "_invariant"):
                    self._invariants[attr._invariant][name] = attr

    def defaults(self) -> None:
        """Placeholder for defaults.

        Override in subclass when an attribute's default depends on other attribute values.
        """

    # ------------------------------------------------------------------
    # Invariant checks
    # ------------------------------------------------------------------
    def _run_invariants(
        self, stage: str, return_errors: bool = False
    ) -> dict[str, list[str]] | None:
        """Run invariants for a given stage. Collect and return/raise errors."""
        if self._disable_invariant_checks:
            return {} if return_errors else None

        errors: dict[str, list[str]] = defaultdict(list)

        for invariant_method in self._invariants.get(stage, {}).values():
            try:
                invariant_method(self)
            except ValidationError as err:
                for field_name in err.messages:
                    errors[field_name].extend(err.messages[field_name])

        if return_errors:
            return dict(errors) if errors else {}

        if errors:
            raise ValidationError(errors)

        return None

    def _precheck(self, return_errors: bool = False):
        """Invariant checks performed before entity changes."""
        return self._run_invariants("pre", return_errors=return_errors)

    def _postcheck(self, return_errors: bool = False):
        """Invariant checks performed after initialization and attribute changes."""
        return self._run_invariants("post", return_errors=return_errors)

    # ------------------------------------------------------------------
    # Mutation with validation + invariant checks
    # ------------------------------------------------------------------
    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__class__.model_fields and getattr(self, "_initialized", False):
            # Determine the target for invariant checks: aggregate root or self
            target = self._root if self._root is not None else self

            # Pre-check invariants
            target._precheck()

            # Delegate to Pydantic (validates via validate_assignment)
            try:
                super().__setattr__(name, value)
            except PydanticValidationError as e:
                from protean.core.value_object import _convert_pydantic_errors

                raise ValidationError(_convert_pydantic_errors(e))

            # Post-check invariants
            target._postcheck()

            # Mark entity state as changed
            self._state.mark_changed()
        elif getattr(self, "_initialized", False) and (
            self._get_class_descriptor(type(self), name) is not None
        ):
            # Descriptor field: use object.__setattr__ to trigger descriptor protocol
            target = self._root if self._root is not None else self
            target._precheck()
            object.__setattr__(self, name, value)
            target._postcheck()
            self._state.mark_changed()
        elif name.startswith(("add_", "remove_", "get_one_from_", "filter_")):
            # Association pseudo-methods set during model_post_init
            object.__setattr__(self, name, value)
        else:
            super().__setattr__(name, value)

    # ------------------------------------------------------------------
    # Hierarchy management
    # ------------------------------------------------------------------
    def _set_root_and_owner(self, root: Any, owner: Any) -> None:
        """Set the root and owner entities.

        Recursively descends into child entities to propagate the aggregate
        root reference.  Uses ``getattr`` so that descriptor-managed values
        (stored in ``state_.fields_cache``) are reached correctly.
        """
        self._root = root
        self._owner = owner

        for field_name, field_obj in association_fields(self).items():
            if isinstance(field_obj, HasMany):
                items = getattr(self, field_name, None) or []
                for item in items:
                    item._set_root_and_owner(root, self)
            elif isinstance(field_obj, HasOne):
                item = getattr(self, field_name, None)
                if item is not None:
                    item._set_root_and_owner(root, self)

    # ------------------------------------------------------------------
    # Event raising (delegates to aggregate root)
    # ------------------------------------------------------------------
    def raise_(self, event: Any) -> None:
        """Raise an event in the aggregate cluster.

        The event is always registered on the aggregate root, irrespective
        of where it is raised in the entity cluster.
        """
        if event.meta_.part_of != self._root.__class__:
            raise ConfigurationError(
                f"Event `{event.__class__.__name__}` is not associated with"
                f" aggregate `{self._root.__class__.__name__}`"
            )

        # Delegate to the root aggregate's raise_ (BaseAggregate overrides this)
        self._root.raise_(event)

    # ------------------------------------------------------------------
    # Identity-based equality
    # ------------------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False

        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        if id_field_name is None:
            return False

        return getattr(self, id_field_name) == getattr(other, id_field_name)

    def __hash__(self) -> int:
        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        if id_field_name is None:
            return id(self)
        return hash(getattr(self, id_field_name))

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return entity data as a dictionary.

        Internal fields (prefixed with ``_``, e.g. ``_version``) are excluded.
        Reference fields are skipped (they are navigation, not data).
        ValueObject fields are included only when non-None.
        """
        result: dict[str, Any] = {}
        for fname, field_obj in getattr(self, _FIELDS, {}).items():
            if fname.startswith("_"):
                continue
            if isinstance(field_obj, Reference):
                continue

            value = getattr(self, fname, None)

            if isinstance(field_obj, ValueObject):
                # Only include non-None value objects
                dict_value = field_obj.as_dict(value)
                if dict_value:
                    result[fname] = dict_value
            elif isinstance(field_obj, Association):
                # HasOne/HasMany: delegate to descriptor's as_dict
                result[fname] = field_obj.as_dict(value)
            else:
                result[fname] = field_obj.as_dict(value)
        return result

    @property
    def state_(self) -> _EntityState:
        """Access entity lifecycle state."""
        return self._state

    @state_.setter
    def state_(self, value: _EntityState) -> None:
        self._state = value

    def __repr__(self) -> str:
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self) -> str:
        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        if id_field_name:
            identifier = getattr(self, id_field_name)
            return "%s object (%s)" % (
                self.__class__.__name__,
                "{}: {}".format(id_field_name, identifier),
            )
        return "%s object" % self.__class__.__name__


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def entity_factory(element_cls, domain, **opts):
    """Factory method to create an entity class.

    This method is used to create an entity class. It is called during domain registration.
    """
    # If opts has a `limit` key and it is negative, set it to None
    if "limit" in opts and opts["limit"] is not None and opts["limit"] < 0:
        opts["limit"] = None

    # Determine the correct base class
    if issubclass(element_cls, BaseEntity):
        base_cls = BaseEntity
    else:
        base_cls = _LegacyBaseEntity

    # Derive the entity class from the base entity class
    element_cls = derive_element_class(element_cls, base_cls, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Entity `{element_cls.__name__}` needs to be associated with an Aggregate"
        )

    # Reference auto-creation and shadow fields only apply to legacy entities
    if issubclass(element_cls, _LegacyBaseEntity):
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
                    field_name = inflection.underscore(
                        element_cls.meta_.part_of.__name__
                    )

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
    #   Uses MRO scan for Pydantic entities, inspect.getmembers for legacy
    if issubclass(element_cls, BaseEntity):
        for klass in element_cls.__mro__:
            for method_name, method in vars(klass).items():
                if (
                    not (method_name.startswith("__") and method_name.endswith("__"))
                    and callable(method)
                    and hasattr(method, "_invariant")
                ):
                    element_cls._invariants[method._invariant][method_name] = method
    else:
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
