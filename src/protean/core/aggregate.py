"""Aggregate module providing the base class for aggregate root entities."""

import functools
import inspect
import logging
import typing
from collections import defaultdict
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar, Optional, TypeVar, cast

from pydantic import Field as PydanticField
from pydantic import PrivateAttr
from pydantic_core import PydanticUndefined

from protean._deprecation import warn_deprecated
from protean.core.entity import BaseEntity, _EntityState
from protean.core.value_object import value_object_from_entity
from protean.fields.tempdata import AssociationCache
from protean.core.event import BaseEvent
from protean.fields.resolved import ResolvedField
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import HasMany, HasOne, Reference, ValueObject
from protean.fields.basic import ValueObjectList
from protean.utils import (
    DomainObjects,
    Processing,
    derive_element_class,
    fqn,
    generate_identity,
    inflection,
)
from protean.utils.container import DerivedDefault
from protean.utils.eventing import DomainMeta, MessageEnvelope, MessageHeaders, Metadata
from protean.utils.globals import current_domain
from protean.utils.reflection import (
    _FIELDS,
    _ID_FIELD_NAME,
    association_fields,
    fields,
    reference_fields,
    value_object_fields,
)
from protean.utils.telemetry import inject_traceparent_from_context

logger = logging.getLogger(__name__)


class BaseAggregate(BaseEntity):
    """Base class for aggregate root entities -- the primary building block for
    modeling domain concepts.

    Aggregates enforce consistency rules and define transaction boundaries.
    They inherit all entity capabilities (fields, identity, invariants) and add
    versioning for optimistic concurrency, event raising via ``raise_()``, and
    event-sourcing support via ``_apply()`` / ``from_events()``.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``is_event_sourced`` | ``bool`` | Enable event-sourcing mode (default: ``False``). |
    | ``fact_events`` | ``bool`` | Auto-generate fact events on persistence (default: ``False``). |
    | ``stream_category`` | ``str`` | Override the event stream category name. |
    | ``provider`` | ``str`` | The persistence provider name (default: ``"default"``). |
    | ``schema_name`` | ``str`` | The storage table/collection name. |
    | ``auto_add_id_field`` | ``bool`` | Whether to auto-inject an ``id`` field (default: ``True``). |
    """

    element_type: ClassVar[str] = DomainObjects.AGGREGATE

    # Version tracking (PrivateAttr)
    _version: int = PrivateAttr(default=-1)
    _next_version: int = PrivateAttr(default=0)
    _event_position: int = PrivateAttr(default=-1)

    # Temporal query marker — set when aggregate is loaded via
    # ``repo.get(id, at_version=...)`` or ``repo.get(id, as_of=...)``.
    # Temporal aggregates are read-only: ``raise_()`` will refuse new events.
    _is_temporal: bool = PrivateAttr(default=False)

    # Event sourcing maps (ClassVar — populated by factory)
    _projections: ClassVar[defaultdict[str, set[Any]]] = defaultdict(set)
    _events_cls_map: ClassVar[dict[str, Any]] = {}

    if TYPE_CHECKING:
        # Assigned per-subclass by the fact-event factory via
        # ``setattr(element_cls, "_fact_event_cls", event_cls)`` when the
        # aggregate opts into fact events; declared here only so static
        # checkers see the attribute.
        _fact_event_cls: ClassVar[type[BaseEvent]]

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseAggregate":
        if cls is BaseAggregate:
            raise NotSupportedError("BaseAggregate cannot be instantiated")
        return cast("BaseAggregate", super().__new__(cls, *args, **kwargs))

    _default_options: ClassVar[list[tuple[str, Any]]] = [
        ("abstract", False),
        ("aggregate_cluster", None),
        ("auto_add_id_field", True),
        ("fact_events", False),
        ("indexes", ()),
        ("is_event_sourced", False),
        ("database_model", None),
        ("provider", "default"),
        (
            "schema_name",
            DerivedDefault(lambda cls: inflection.underscore(cls.__name__)),
        ),
        (
            "stream_category",
            DerivedDefault(lambda cls: inflection.underscore(cls.__name__)),
        ),
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

        fields_dict = getattr(cls, _FIELDS, {})
        fields_dict["_version"] = ResolvedField("_version", None, int)
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
        # Guard: temporal aggregates are read-only
        if self._is_temporal:
            raise IncorrectUsageError(
                "Cannot raise events on a temporally-loaded aggregate. "
                "Temporal aggregates are read-only."
            )

        # Verify that event is associated with this aggregate
        if event.meta_.part_of != self.__class__:
            raise ConfigurationError(
                f"Event `{event.__class__.__name__}` is not associated with"
                f" aggregate `{self.__class__.__name__}`"
            )

        # Warn once per type when a deprecated event is raised.
        self._warn_if_deprecated(event.__class__)

        id_field_name = getattr(self.__class__, _ID_FIELD_NAME, None)
        identifier = getattr(self, id_field_name) if id_field_name else None

        # Set Fact Event stream to be `<aggregate_stream_name>-fact`
        if event.__class__.meta_.is_fact_event:
            stream = f"{self.meta_.stream_category}-fact-{identifier}"
        else:
            stream = f"{self.meta_.stream_category}-{identifier}"

        if self.meta_.is_event_sourced:
            if not event.__class__.meta_.is_fact_event:
                self._version += 1

            event_identity = f"{stream}-{self._version}"
            sequence_id = f"{self._version}"
        else:
            aggregate_version = max(self._version, self._next_version)
            event_number = len(self._events) + 1

            event_identity = f"{stream}-{aggregate_version}.{event_number}"
            sequence_id = f"{aggregate_version}.{event_number}"

        # Carry forward an existing traceparent from the event's original
        # metadata, or inject the current OTEL span context so that events
        # raised during handler execution remain part of the distributed trace.
        traceparent = (
            event._metadata.headers.traceparent
            if event._metadata.headers and event._metadata.headers.traceparent
            else None
        )
        if traceparent is None:
            traceparent = inject_traceparent_from_context()

        headers = MessageHeaders(
            id=event_identity,
            type=event.__class__.__type__,
            stream=stream,
            time=event._metadata.headers.time
            if (event._metadata.headers and event._metadata.headers.time)
            else None,
            traceparent=traceparent,
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

        # Run event enrichers
        if current_domain._event_enrichers:
            extensions = dict(metadata.extensions)
            for enricher in current_domain._event_enrichers:
                result = enricher(event, self)
                if result:
                    extensions.update(result)
            if extensions:
                metadata = Metadata(
                    headers=metadata.headers,
                    envelope=metadata.envelope,
                    domain=metadata.domain,
                    event_store=metadata.event_store,
                    extensions=extensions,
                )

        event_with_metadata = event.__class__(
            event.payload,
            _expected_version=self._event_position,
            _metadata=metadata,
        )

        self._event_position = self._event_position + 1
        self._events.append(event_with_metadata)

        # For ES aggregates, apply the event handler to mutate state in-place.
        # This makes @apply the single source of truth for state changes —
        # the same code path used during live processing and event replay.
        # We use atomic_change so that invariants are checked before and
        # after the handler runs, preserving the "always valid" guarantee.
        if self.meta_.is_event_sourced:
            if not event.__class__.meta_.is_fact_event:
                with atomic_change(self):
                    self._apply_handler(event_with_metadata)

    @staticmethod
    def _warn_if_deprecated(event_cls: type[BaseEvent]) -> None:
        """Emit a raise-time deprecation warning for a deprecated event.

        Routes through :func:`protean._deprecation.warn_deprecated`. Fires at
        most once per event type per domain (tracked on the domain, which is
        fresh per run) to avoid log spam when the event is raised many times.
        Names the ``superseded_by`` replacement when one is declared.
        """
        deprecated = event_cls.meta_.deprecated
        if not deprecated:
            return

        warned = current_domain._deprecated_events_warned
        if event_cls in warned:
            return
        warned.add(event_cls)

        superseded_by = event_cls.meta_.superseded_by
        alternative = None
        if superseded_by is not None:
            successor = (
                superseded_by.__name__
                if isinstance(superseded_by, type)
                else superseded_by
            )
            alternative = f"Use `{successor}` instead."

        warn_deprecated(
            f"Event `{event_cls.__name__}`",
            removal=deprecated.get("removal"),
            alternative=alternative,
            stacklevel=3,
        )

    def _apply_handler(self, event: Any) -> None:
        """Invoke @apply handler(s) for an event without version management.

        Extracted from ``_apply()`` so that ``raise_()`` can call handlers
        during the live path without double-incrementing ``_version``.

        Every event raised by an ES aggregate MUST have a corresponding
        ``@apply`` handler — there is no silent fallback.
        """
        event_name = fqn(event.__class__)

        if event_name not in self._projections:
            raise IncorrectUsageError(
                f"No @apply handler registered for event `{event_name}` "
                f"in `{self.__class__.__name__}`"
            )

        for fn in self._projections[event_name]:
            fn(self, event)

    def _apply(self, event: Any) -> None:
        """Event-Sourcing: apply an event during replay.

        Calls the handler then increments ``_version`` once per event.
        """
        self._apply_handler(event)
        self._version += 1

    @classmethod
    def _create_for_reconstitution(cls) -> "BaseAggregate":
        """Create a blank aggregate for event replay, bypassing field validation.

        Uses ``__new__`` to skip ``__init__`` entirely (no Pydantic validation,
        no required field checks).  Sets up internal plumbing so that
        ``@apply`` handlers can mutate fields via normal ``__setattr__``.

        Follows the same pattern as ``BaseEntity.__deepcopy__`` (entity.py).
        """

        aggregate = cls.__new__(cls)

        # --- Pydantic internals (same pattern as __deepcopy__) ---
        object.__setattr__(aggregate, "__dict__", {})
        object.__setattr__(aggregate, "__pydantic_extra__", None)
        object.__setattr__(aggregate, "__pydantic_fields_set__", set())

        # --- Private attributes with defaults ---
        private = {
            "_version": -1,
            "_next_version": 0,
            "_event_position": -1,
            "_is_temporal": False,
            "_initialized": False,
            "_state": _EntityState(),
            "_root": None,
            "_owner": None,
            "_temp_cache": AssociationCache(),
            "_events": [],
            "_disable_invariant_checks": True,  # Suppress during replay
            "_invariants": defaultdict(dict),
        }
        object.__setattr__(aggregate, "__pydantic_private__", private)

        aggregate._root = aggregate
        aggregate._owner = aggregate

        # --- Initialize all model fields to None ---
        for fname in cls.model_fields:
            aggregate.__dict__[fname] = None  # pyright: ignore[reportIndexIssue]

        # --- Initialize VO shadow fields ---
        # ``value_object_fields`` filters on ``ValueObject`` at runtime, so each
        # field carries ``get_shadow_fields``; narrow the generic ``Field`` type.
        for vo_field in value_object_fields(cls).values():
            for _, shadow_field in cast(ValueObject, vo_field).get_shadow_fields():
                # ``attribute_name`` is ``str | None`` on the base field but is
                # always resolved to a concrete name by reconstitution time.
                assert shadow_field.attribute_name is not None
                aggregate.__dict__[shadow_field.attribute_name] = None  # pyright: ignore[reportIndexIssue]

        # --- Initialize Reference shadow fields ---
        # ``reference_fields`` filters on ``Reference`` at runtime, so each field
        # carries ``get_shadow_field``; narrow the generic ``Field`` type.
        for ref_field in reference_fields(cls).values():
            shadow_name, _ = cast(Reference, ref_field).get_shadow_field()
            # ``shadow_name`` is ``str | None`` but always resolved for a bound
            # reference field, so this assert never fires at runtime.
            assert shadow_name is not None  # pragma: no cover
            aggregate.__dict__[shadow_name] = None  # pyright: ignore[reportIndexIssue]

        # --- Setup association pseudo-methods (add_*, remove_*, etc.) ---
        for field_name, field_obj in association_fields(cls).items():
            if isinstance(field_obj, HasMany):
                setattr(
                    aggregate,
                    f"add_{field_name}",
                    partial(field_obj.add, aggregate),
                )
                setattr(
                    aggregate,
                    f"remove_{field_name}",
                    partial(field_obj.remove, aggregate),
                )
                setattr(
                    aggregate,
                    f"get_one_from_{field_name}",
                    partial(field_obj.get, aggregate),
                )
                setattr(
                    aggregate,
                    f"filter_{field_name}",
                    partial(field_obj.filter, aggregate),
                )

        # --- Discover invariants from MRO ---
        aggregate._discover_invariants()

        aggregate._initialized = True
        return aggregate

    @classmethod
    def _create_new(cls, **identity_kwargs: Any) -> "BaseAggregate":
        """Create a new ES aggregate with auto-generated identity.

        Used by factory methods.  All state beyond identity will be
        established by the creation event's ``@apply`` handler via
        ``raise_()``.

        This avoids the need to pass every required field to the constructor
        just to satisfy Pydantic validation — only identity is needed::

            order = Order._create_new()
            order.raise_(OrderCreated(order_id=str(order.id), ...))
        """
        aggregate = cls._create_for_reconstitution()
        aggregate._disable_invariant_checks = False  # Enable for live path

        # Set identity — either from kwargs or auto-generate
        id_field_name = getattr(cls, _ID_FIELD_NAME)
        if id_field_name in identity_kwargs:
            aggregate.__dict__[id_field_name] = identity_kwargs[id_field_name]  # pyright: ignore[reportIndexIssue]
        else:
            aggregate.__dict__[id_field_name] = generate_identity()  # pyright: ignore[reportIndexIssue]

        return aggregate

    @classmethod
    def from_events(cls, events: list[Any]) -> "BaseAggregate":
        """Event-Sourcing: reconstruct an aggregate from a list of events.

        Creates a blank aggregate via ``_create_for_reconstitution()`` and
        applies all events uniformly through ``_apply()``.  The first event's
        ``@apply`` handler must set ALL fields including identity.

        Raises:
            IncorrectUsageError: If ``events`` is empty — an aggregate cannot
                be reconstructed without at least one event.
        """
        if not events:
            raise IncorrectUsageError(
                f"Cannot reconstitute `{cls.__name__}` from an empty event list"
            )

        aggregate = cls._create_for_reconstitution()

        for event in events:
            aggregate._apply(event)

        aggregate._disable_invariant_checks = False
        return aggregate


# ---------------------------------------------------------------------------
# Fact Event Conversion
# ---------------------------------------------------------------------------
def element_to_fact_event(element_cls: type[Any]) -> Any:
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


def _pydantic_element_to_fact_event(element_cls: type[Any]) -> Any:
    """Pydantic path: create fact events using Pydantic annotations and BaseModel.

    Returns either a ``ValueObject`` field descriptor (entity path) or a
    dynamically-built ``type[BaseEvent]`` (aggregate path).  Typed ``Any``
    because both branches flow through the untyped ``ValueObject`` field
    factory / dynamic ``type()`` construction.
    """
    if element_cls.element_type == DomainObjects.ENTITY:
        # Entity → Value Object: delegate to the shared utility
        vo_cls = value_object_from_entity(element_cls)
        return ValueObject(value_object_cls=vo_cls)

    # Aggregate → Fact Event
    annotations: dict[str, Any] = {}
    namespace: dict[str, Any] = {}
    association_descriptors: dict[str, ValueObject | ValueObjectList] = {}
    model_field_info = getattr(element_cls, "model_fields", {})

    for key, value in fields(element_cls).items():
        if isinstance(value, Reference):
            continue

        # Skip internal fields (e.g. _version) — Pydantic treats _ prefix as private
        if key.startswith("_"):
            continue

        if isinstance(value, HasOne):
            # Recursively convert entity to VO. ``to_cls`` is typed ``str | type``
            # because associations carry a string reference during registration;
            # by the time fact events are built (domain init, post-resolution) it
            # is always the resolved target class.
            assert not isinstance(value.to_cls, str)
            result = element_to_fact_event(value.to_cls)
            vo_descriptor = (
                result
                if isinstance(result, ValueObject)
                else ValueObject(value_object_cls=result)
            )
            vo_cls = vo_descriptor.value_object_cls
            annotations[key] = Optional[vo_cls]
            namespace[key] = None
            association_descriptors[key] = vo_descriptor

        elif isinstance(value, HasMany):
            # Recursively convert entity to list of VOs. ``to_cls`` is resolved to
            # the target class by the time fact events are built (see above).
            assert not isinstance(value.to_cls, str)
            result = element_to_fact_event(value.to_cls)
            vo_descriptor = (
                result
                if isinstance(result, ValueObject)
                else ValueObject(value_object_cls=result)
            )
            list_descriptor = ValueObjectList(content_type=vo_descriptor)
            vo_cls = vo_descriptor.value_object_cls
            # Dynamic generic alias built from a runtime-derived VO class for
            # Pydantic's annotations; mypy cannot treat a variable as a type here.
            annotations[key] = list[vo_cls]  # type: ignore[valid-type]
            namespace[key] = PydanticField(default_factory=list)
            association_descriptors[key] = list_descriptor

        elif isinstance(value, ValueObject):
            # Legacy-style VO descriptor in a Pydantic element. ``value_object_cls``
            # is typed ``type[BaseValueObject] | str`` for the same registration-time
            # reason; it is the resolved class at fact-event build time.
            assert not isinstance(value.value_object_cls, str)
            vo_cls = value.value_object_cls
            annotations[key] = Optional[vo_cls]
            namespace[key] = None
            association_descriptors[key] = value

        elif isinstance(value, ResolvedField):
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


_T = TypeVar("_T")


def aggregate_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
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

    # The derived class is always a ``BaseAggregate`` subclass at runtime;
    # narrow the unbound ``type[_T]`` typevar so the injected class attributes
    # (``_invariants``, ``meta_``, ``_projections``, ``_events_cls_map``) are
    # visible to both type checkers.
    aggregate_cls = cast("type[BaseAggregate]", element_cls)

    # Iterate through methods marked as `@invariant` and record them for later use
    for klass in aggregate_cls.__mro__:
        for method_name, method in vars(klass).items():
            if (
                not (method_name.startswith("__") and method_name.endswith("__"))
                and callable(method)
                and hasattr(method, "_invariant")
            ):
                aggregate_cls._invariants[getattr(method, "_invariant")][
                    method_name
                ] = method

    # Set stream category to be `domain_name::aggregate_name`
    aggregate_cls.meta_.stream_category = (
        f"{domain.normalized_name}::{aggregate_cls.meta_.stream_category}"
    )

    # Event-Sourcing Functionality
    # Iterate through methods marked as `@apply` and construct a projections map
    for klass in aggregate_cls.__mro__:
        for method_name, method in vars(klass).items():
            if (
                not (method_name.startswith("__") and method_name.endswith("__"))
                and callable(method)
                and hasattr(method, "_event_cls")
            ):
                event_cls = getattr(method, "_event_cls")
                aggregate_cls._projections[fqn(event_cls)].add(method)
                aggregate_cls._events_cls_map[fqn(event_cls)] = event_cls

    return element_cls


class atomic_change:
    """Context manager to temporarily disable invariant checks on aggregate.

    Also captures status field snapshots on entry and validates the
    overall start-to-end transition on exit — so batched mutations
    (and ``@apply`` handlers in ES aggregates) are validated as a single
    logical transition.
    """

    def __init__(self, aggregate: Any) -> None:
        self.aggregate = aggregate
        self._status_snapshots: dict[str, Any] = {}

    def __enter__(self) -> None:
        # Capture status field snapshots BEFORE precheck
        self._capture_status_snapshots()
        # Temporary disable invariant checks
        self.aggregate._precheck()
        self.aggregate._disable_invariant_checks = True

    def __exit__(self, exc_type: Any, *args: Any) -> None:
        # Re-enable invariant checks
        self.aggregate._disable_invariant_checks = False

        # Validate status transitions (start -> end) before post-invariants.
        # Only validate when no exception is being propagated.
        if exc_type is None:
            self._validate_status_transitions()

        self.aggregate._postcheck()

    def _capture_status_snapshots(self) -> None:
        """Snapshot all status fields with transition rules."""
        fields_dict = getattr(self.aggregate.__class__, _FIELDS, {})
        for fname, fobj in fields_dict.items():
            if isinstance(fobj, ResolvedField) and getattr(fobj, "transitions", None):
                self._status_snapshots[fname] = getattr(self.aggregate, fname, None)

    def _validate_status_transitions(self) -> None:
        """Validate start-to-end status transitions within the atomic block."""
        fields_dict = getattr(self.aggregate.__class__, _FIELDS, {})

        for fname, start_value in self._status_snapshots.items():
            fobj = fields_dict.get(fname)
            if fobj is None or not isinstance(fobj, ResolvedField):
                continue

            end_value = getattr(self.aggregate, fname, None)

            start = start_value.value if isinstance(start_value, Enum) else start_value
            end = end_value.value if isinstance(end_value, Enum) else end_value

            if start == end or start is None:
                continue

            transitions = fobj.transitions
            if transitions is None:
                continue

            if start not in transitions:
                raise ValidationError(
                    {
                        fname: [
                            f"Invalid status transition from '{start}'. "
                            f"'{start}' is a terminal state with no "
                            f"allowed transitions"
                        ]
                    }
                )

            allowed = transitions[start]
            if end not in allowed:
                allowed_str = ", ".join(allowed)
                raise ValidationError(
                    {
                        fname: [
                            f"Invalid status transition from '{start}' "
                            f"to '{end}'. "
                            f"Allowed transitions: {allowed_str}"
                        ]
                    }
                )


_F = TypeVar("_F", bound=typing.Callable[..., None])


def apply(fn: _F) -> _F:
    """Decorator to mark event-application methods on Event-Sourced Aggregates.

    Each ``@apply`` method handles one event type and mutates aggregate state
    accordingly.  The method must accept a single argument annotated with the
    event class::

        @apply
        def deposited(self, event: Deposited) -> None:
            self.balance += event.amount
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
    def wrapper(*args: Any) -> None:
        fn(*args)

    setattr(wrapper, "_event_cls", _event_cls)

    return wrapper  # type: ignore[return-value]
