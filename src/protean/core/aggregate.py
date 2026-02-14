"""Aggregate Functionality and Classes"""

from __future__ import annotations

import functools
import inspect
import logging
import typing
from collections import defaultdict
from typing import Any, ClassVar

from pydantic import PrivateAttr

from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.value_object import (
    BaseValueObject,
    _FieldShim,
)
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.fields import HasMany, HasOne, Reference, ValueObject
from protean.fields.basic import ValueObjectList
from protean.utils import (
    DomainObjects,
    Processing,
    derive_element_class,
    fqn,
    inflection,
)
from protean.utils.eventing import DomainMeta, MessageEnvelope, MessageHeaders, Metadata
from protean.utils.globals import current_domain
from protean.utils.reflection import _FIELDS, _ID_FIELD_NAME, fields

logger = logging.getLogger(__name__)


class BaseAggregate(BaseEntity):
    """Base class for Aggregate root entities.

    Inherits from ``BaseEntity``. Adds versioning, event raising (``raise_``),
    event sourcing (``_apply`` / ``from_events``), and projection dispatch.
    """

    element_type: ClassVar[str] = DomainObjects.AGGREGATE

    # Version tracking (PrivateAttr)
    _version: int = PrivateAttr(default=-1)
    _next_version: int = PrivateAttr(default=0)
    _event_position: int = PrivateAttr(default=-1)

    # Event sourcing maps (ClassVar — populated by factory)
    _projections: ClassVar[dict] = defaultdict(set)
    _events_cls_map: ClassVar[dict] = {}

    def __new__(cls, *args: Any, **kwargs: Any) -> BaseAggregate:
        if cls is BaseAggregate:
            raise NotSupportedError("BaseAggregate cannot be instantiated")
        return super().__new__(cls, *args, **kwargs)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [
            ("abstract", False),
            ("aggregate_cluster", None),
            ("auto_add_id_field", True),
            ("fact_events", False),
            ("is_event_sourced", False),
            ("database_model", None),
            ("provider", "default"),
            ("schema_name", inflection.underscore(cls.__name__)),
            ("stream_category", inflection.underscore(cls.__name__)),
            ("limit", 100),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Event-Sourcing: per-subclass projection map and events class map
        setattr(cls, "_projections", defaultdict(set))
        setattr(cls, "_events_cls_map", {})

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Called by Pydantic AFTER model_fields are fully populated.

        Extends the parent hook to inject ``_version`` into
        ``__container_fields__`` so that it is persisted and round-tripped
        through the repository layer (needed for optimistic concurrency).
        """
        super().__pydantic_init_subclass__(**kwargs)

        from protean.core.value_object import _FieldShim

        fields_dict = getattr(cls, _FIELDS, {})
        fields_dict["_version"] = _FieldShim("_version", None, int)
        setattr(cls, _FIELDS, fields_dict)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Pop _version before Pydantic init (it's a PrivateAttr,
        # and extra="forbid" would reject it). Restore after construction.
        # Check both kwargs and positional dict args (template dict pattern).
        version = kwargs.pop("_version", None)
        if version is None:
            for arg in args:
                if isinstance(arg, dict) and "_version" in arg:
                    version = arg.pop("_version")
                    break
        if version is None:
            version = -1

        super().__init__(*args, **kwargs)

        # Restore _version from kwargs or default
        self._version = version

        # Set self as root and owner
        self._set_root_and_owner(self, self)

        # Increment version and set next version
        self._next_version = self._version + 1

    def raise_(self, event: Any) -> None:
        """Raise a domain event on this aggregate.

        Enriches the event with metadata (identity, stream, sequence,
        checksum) and appends it to ``self._events``.
        """
        # Verify that event is associated with this aggregate
        if event.meta_.part_of != self.__class__:
            raise ConfigurationError(
                f"Event `{event.__class__.__name__}` is not associated with"
                f" aggregate `{self.__class__.__name__}`"
            )

        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        identifier = getattr(self, id_field_name) if id_field_name else None

        # Set Fact Event stream to be `<aggregate_stream_name>-fact`
        if event.__class__.__name__.endswith("FactEvent"):
            stream = f"{self.meta_.stream_category}-fact-{identifier}"
        else:
            stream = f"{self.meta_.stream_category}-{identifier}"

        if self.meta_.is_event_sourced:
            if not event.__class__.__name__.endswith("FactEvent"):
                self._version += 1

            event_identity = f"{stream}-{self._version}"
            sequence_id = f"{self._version}"
        else:
            aggregate_version = max(self._version, self._next_version)
            event_number = len(self._events) + 1

            event_identity = f"{stream}-{aggregate_version}.{event_number}"
            sequence_id = f"{aggregate_version}.{event_number}"

        headers = MessageHeaders(
            id=event_identity,
            type=event.__class__.__type__,
            stream=stream,
            time=event._metadata.headers.time
            if (event._metadata.headers and event._metadata.headers.time)
            else None,
        )

        envelope = MessageEnvelope.build(event.payload)

        domain_meta = DomainMeta(
            **{
                **event._metadata.domain.to_dict(),
                "stream_category": self.meta_.stream_category,
                "sequence_id": sequence_id,
                "asynchronous": current_domain.config["event_processing"]
                == Processing.ASYNC.value,
            }
        )

        metadata = Metadata(
            headers=headers,
            envelope=envelope,
            domain=domain_meta,
        )

        event_with_metadata = event.__class__(
            event.payload,
            _expected_version=self._event_position,
            _metadata=metadata,
        )

        self._event_position = self._event_position + 1
        self._events.append(event_with_metadata)

    def _apply(self, event: Any) -> None:
        """Event-Sourcing: apply an event by calling the appropriate projection."""
        event_name = fqn(event.__class__)

        if event_name not in self._projections:
            raise NotImplementedError(
                f"No handler registered for event `{event_name}` in `{self.__class__.__name__}`"
            )

        for fn in self._projections[event_name]:
            fn(self, event)
            self._version += 1

    @classmethod
    def from_events(cls, events: list) -> BaseAggregate:
        """Event-Sourcing: reconstruct an aggregate from a list of events."""
        aggregate = cls(**events[0].payload)
        aggregate._apply(events[0])

        for event in events[1:]:
            aggregate._apply(event)

        return aggregate


# ---------------------------------------------------------------------------
# Fact Event Conversion
# ---------------------------------------------------------------------------
def element_to_fact_event(element_cls):
    """Convert an Element to a Fact Event.

    This is a helper function to convert an Element to a Fact Event. Fact Events are used to
    store the state of an Aggregate Element at a point in time. This function is used during
    domain initialization to detect aggregates that have registered for fact events generation.

    Associations are converted to Value Objects:
    1. A `HasOne` association is replaced with a Value Object.
    2. A `HasMany` association is replaced with a List of Value Objects.

    The target class of associations is constructed as the Value Object.
    """
    return _pydantic_element_to_fact_event(element_cls)


def _pydantic_element_to_fact_event(element_cls):
    """Pydantic path: create fact events using Pydantic annotations and BaseModel."""
    from pydantic import Field as PydanticField
    from pydantic_core import PydanticUndefined

    annotations: dict[str, Any] = {}
    namespace: dict[str, Any] = {}
    # Track association descriptors (ValueObject / List) so we can inject them
    # into ``__container_fields__`` after the class is created.  This keeps
    # the introspection API compatible with the legacy path.
    association_descriptors: dict[str, ValueObject | ValueObjectList] = {}
    model_field_info = getattr(element_cls, "model_fields", {})

    for key, value in fields(element_cls).items():
        if isinstance(value, Reference):
            continue

        # Skip internal fields (e.g. _version) — Pydantic treats _ prefix as private
        if key.startswith("_"):
            continue

        if isinstance(value, HasOne):
            # Recursively convert entity to VO
            result = element_to_fact_event(value.to_cls)
            vo_descriptor = (
                result
                if isinstance(result, ValueObject)
                else ValueObject(value_object_cls=result)
            )
            vo_cls = vo_descriptor.value_object_cls
            annotations[key] = vo_cls | None
            namespace[key] = None
            association_descriptors[key] = vo_descriptor

        elif isinstance(value, HasMany):
            # Recursively convert entity to list of VOs
            result = element_to_fact_event(value.to_cls)
            vo_descriptor = (
                result
                if isinstance(result, ValueObject)
                else ValueObject(value_object_cls=result)
            )
            list_descriptor = ValueObjectList(content_type=vo_descriptor)
            vo_cls = vo_descriptor.value_object_cls
            annotations[key] = list[vo_cls]
            namespace[key] = PydanticField(default_factory=list)
            association_descriptors[key] = list_descriptor

        elif isinstance(value, ValueObject):
            # Legacy-style VO descriptor in a Pydantic element
            vo_cls = value.value_object_cls
            annotations[key] = vo_cls | None
            namespace[key] = None
            association_descriptors[key] = value

        elif isinstance(value, _FieldShim):
            # Regular Pydantic model field
            finfo = model_field_info.get(key)
            if finfo:
                annotations[key] = finfo.annotation
                if finfo.default is not PydanticUndefined:
                    namespace[key] = finfo.default
                elif finfo.default_factory is not None:
                    namespace[key] = PydanticField(
                        default_factory=finfo.default_factory
                    )
                # else: required field — no default needed
            else:
                annotations[key] = Any
                namespace[key] = None

    if element_cls.element_type == DomainObjects.ENTITY:
        # Entity → Value Object conversion.
        # Strip identifier/unique: make those fields optional with None default.
        container_fields = fields(element_cls)
        for key in list(annotations.keys()):
            field_obj = container_fields.get(key)
            if isinstance(field_obj, _FieldShim) and (
                field_obj.identifier or field_obj.unique
            ):
                annotations[key] = annotations[key] | None
                namespace[key] = None

        ns = {"__annotations__": annotations, **namespace}
        value_object_cls = type(
            f"{element_cls.__name__}ValueObject",
            (BaseValueObject,),
            ns,
        )

        # Inject association descriptors into __container_fields__
        cf = getattr(value_object_cls, _FIELDS, {})
        cf.update(association_descriptors)
        setattr(value_object_cls, _FIELDS, cf)

        return ValueObject(value_object_cls=value_object_cls)

    # Aggregate → Fact Event
    ns = {"__annotations__": annotations, **namespace}
    event_cls = type(
        f"{element_cls.__name__}FactEvent",
        (BaseEvent,),
        ns,
    )

    # Inject association descriptors into __container_fields__
    cf = getattr(event_cls, _FIELDS, {})
    cf.update(association_descriptors)
    setattr(event_cls, _FIELDS, cf)

    # Store the fact event class as part of the aggregate itself
    setattr(element_cls, "_fact_event_cls", event_cls)

    # Return the fact event class to be registered with the domain
    return event_cls


def aggregate_factory(element_cls, domain, **opts):
    """Factory method to create an aggregate class.

    This method is used to create an aggregate class. It is called during domain registration.
    """
    # If opts has a `limit` key and it is negative, set it to None
    if "limit" in opts and opts["limit"] is not None and opts["limit"] < 0:
        opts["limit"] = None

    # Always route to Pydantic base
    base_cls = BaseAggregate

    # Derive the aggregate class from the base aggregate class
    element_cls = derive_element_class(element_cls, base_cls, **opts)

    # Iterate through methods marked as `@invariant` and record them for later use
    for klass in element_cls.__mro__:
        for method_name, method in vars(klass).items():
            if (
                not (method_name.startswith("__") and method_name.endswith("__"))
                and callable(method)
                and hasattr(method, "_invariant")
            ):
                element_cls._invariants[method._invariant][method_name] = method

    # Set stream name to be `domain_name::aggregate_name`
    element_cls.meta_.stream_category = (
        f"{domain.normalized_name}::{element_cls.meta_.stream_category}"
    )

    # Event-Sourcing Functionality
    # Iterate through methods marked as `@apply` and construct a projections map
    for klass in element_cls.__mro__:
        for method_name, method in vars(klass).items():
            if (
                not (method_name.startswith("__") and method_name.endswith("__"))
                and callable(method)
                and hasattr(method, "_event_cls")
            ):
                element_cls._projections[fqn(method._event_cls)].add(method)
                element_cls._events_cls_map[fqn(method._event_cls)] = method._event_cls

    return element_cls


class atomic_change:
    """Context manager to temporarily disable invariant checks on aggregate"""

    def __init__(self, aggregate):
        self.aggregate = aggregate

    def __enter__(self):
        # Temporary disable invariant checks
        self.aggregate._precheck()
        self.aggregate._disable_invariant_checks = True

    def __exit__(self, *args):
        # Validate on exit to trigger invariant checks
        self.aggregate._disable_invariant_checks = False
        self.aggregate._postcheck()


def apply(fn):
    """Event-Sourcing Functionality

    Decorator to mark methods in EventHandler classes.
    """

    if len(typing.get_type_hints(fn)) > 2:
        raise IncorrectUsageError(
            f"Handler method `{fn.__name__}` has incorrect number of arguments"
        )

    try:
        _event_cls = next(
            iter(
                {
                    value
                    for value in typing.get_type_hints(fn).values()
                    if inspect.isclass(value) and issubclass(value, BaseEvent)
                }
            )
        )
    except StopIteration:
        raise IncorrectUsageError(
            f"Apply method `{fn.__name__}` should accept an argument annotated with the Event class"
        )

    @functools.wraps(fn)
    def wrapper(*args):
        fn(*args)

    setattr(wrapper, "_event_cls", _event_cls)

    return wrapper
