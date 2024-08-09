"""Aggregate Functionality and Classes"""

import functools
import inspect
import logging
import typing
from collections import defaultdict
from typing import List

from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import HasMany, HasOne, Integer, Reference, ValueObject
from protean.fields import List as ProteanList
from protean.utils import DomainObjects, derive_element_class, fqn, inflection
from protean.utils.reflection import fields

logger = logging.getLogger(__name__)


class BaseAggregate(BaseEntity):
    """This is the base class for Domain Aggregates.

    Aggregates are fundamental, coarse-grained building blocks of a domain model. They are
    conceptual wholes - they enclose all behaviors and data of a distinct domain concept.
    Aggregates are often composed of one or more Aggregate Elements (Entities and Value Objests),
    that work together to codify a concept.

    This class provides helper methods to custom define aggregate attributes, and query attribute
    names during runtime.

    Basic Usage::

        @domain.aggregate
        class Dog:
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

    During persistence, the model associated with this entity is retrieved dynamically from
        the repository factory. A model object is usually pre-initialized with a live DB connection.
    """

    element_type = DomainObjects.AGGREGATE

    def __new__(cls, *args, **kwargs):
        if cls is BaseAggregate:
            raise NotSupportedError("BaseAggregate cannot be instantiated")
        return super().__new__(cls)

    # Track current version of Aggregate
    _version = Integer(default=-1)

    # Temporary variable to track next version of Aggregate
    _next_version = 0

    # Temporary variable to track version of events of Aggregate
    #   This can be different from the version of the Aggregate itself because
    #   a single aggregate update could have triggered multiple events.
    _event_position = -1

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        # Event-Sourcing Functionality
        #
        # Associate a `_projections` map with subclasses.
        #   It needs to be initialized here because if it
        #   were initialized in __init__, the same collection object
        #   would be made available across all subclasses,
        #   defeating its purpose.
        setattr(subclass, "_projections", defaultdict(set))

        # Event-Sourcing Functionality
        #
        # Store associated events
        setattr(subclass, "_events_cls_map", {})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set root in all child elements
        #   This is where we kick-off the process of setting the owner and root
        self._set_root_and_owner(self, self)

        # Increment version and set next version
        self._next_version = self._version + 1

    @classmethod
    def _default_options(cls):
        return [
            ("abstract", False),
            ("aggregate_cluster", None),
            ("auto_add_id_field", True),
            ("fact_events", False),
            ("is_event_sourced", False),
            ("model", None),
            ("provider", "default"),
            ("schema_name", inflection.underscore(cls.__name__)),
            ("stream_category", inflection.underscore(cls.__name__)),
        ]

    def _apply(self, event: BaseEvent) -> None:
        """Event-Sourcing Functionality

        Apply the event onto the aggregate by calling the appropriate projection.

        Args:
            event (BaseEvent): Event object to apply
        """
        # FIXME Handle case of missing projection
        event_name = fqn(event.__class__)

        # FIXME Handle case of missing projection method
        if event_name not in self._projections:
            raise NotImplementedError(
                f"No handler registered for event `{event_name}` in `{self.__class__.__name__}`"
            )

        for fn in self._projections[event_name]:
            # Call event handler method
            fn(self, event)
            self._version += 1

    @classmethod
    def from_events(cls, events: List[BaseEvent]) -> "BaseAggregate":
        """Event-Sourcing Functionality

        Reconstruct an aggregate from a list of events.
        """
        # Initialize the aggregate with the first event's payload and apply it
        aggregate = cls(**events[0].payload)
        aggregate._apply(events[0])

        # Apply the rest of the events
        for event in events[1:]:
            aggregate._apply(event)

        return aggregate


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
    # Gather all fields defined in the element, except References.
    #   We ignore references in event payloads.
    attrs = {
        key: value._clone()
        for key, value in fields(element_cls).items()
        if not isinstance(value, Reference)
    }

    # Recursively convert HasOne and HasMany associations to Value Objects
    for key, value in attrs.items():
        if isinstance(value, HasOne):
            attrs[key] = element_to_fact_event(value.to_cls)
        elif isinstance(value, HasMany):
            attrs[key] = ProteanList(content_type=element_to_fact_event(value.to_cls))

    # If we are dealing with an Entity, we convert it to a Value Object
    #   and return it.
    if element_cls.element_type == DomainObjects.ENTITY:
        for _, attr_value in attrs.items():
            if attr_value.identifier:
                attr_value.identifier = False
            if attr_value.unique:
                attr_value.unique = False

        value_object_cls = type(
            f"{element_cls.__name__}ValueObject",
            (BaseValueObject,),
            attrs,
        )
        value_object_field = ValueObject(value_object_cls=value_object_cls)
        return value_object_field

    # Otherwise, we are dealing with an aggregate. By the time we reach here,
    #   we have already converted all associations in the aggregate to Value Objects.
    #   We can now proceed to construct the Fact Event.
    event_cls = type(
        f"{element_cls.__name__}FactEvent",
        (BaseEvent,),
        attrs,
    )

    # Store the fact event class as part of the aggregate itself
    setattr(element_cls, "_fact_event_cls", event_cls)

    # Return the fact event class to be registered with the domain
    return event_cls


def aggregate_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseAggregate, **opts)

    # Iterate through methods marked as `@invariant` and record them for later use
    #   `_invariants` is a dictionary initialized in BaseEntity.__init_subclass__
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_invariant"):
            element_cls._invariants[method._invariant][method_name] = method

    # Set stream name to be `domain_name::aggregate_name`
    element_cls.meta_.stream_category = (
        f"{domain.normalized_name}::{element_cls.meta_.stream_category}"
    )

    # Event-Sourcing Functionality
    # Iterate through methods marked as `@apply` and construct a projections map
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_event_cls"):
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
