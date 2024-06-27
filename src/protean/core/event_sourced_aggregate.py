import functools
import inspect
import logging
import typing
from collections import defaultdict
from typing import List

from protean.container import BaseContainer, EventedMixin, IdentityMixin, OptionsMixin
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import Integer
from protean.reflection import id_field
from protean.utils import (
    DomainObjects,
    derive_element_class,
    fully_qualified_name,
    inflection,
)

logger = logging.getLogger(__name__)


class BaseEventSourcedAggregate(
    OptionsMixin, IdentityMixin, EventedMixin, BaseContainer
):
    """Base Event Sourced Aggregate class that all EventSourced Aggregates should inherit from.

    The order of inheritance is important. We want BaseContainer to be initialised first followed by
    OptionsMixin (so that `meta_` is in place) before inheriting other mixins."""

    element_type = DomainObjects.EVENT_SOURCED_AGGREGATE

    # Track current version of Aggregate
    _version = Integer(default=-1)

    def __new__(cls, *args, **kwargs):
        if cls is BaseEventSourcedAggregate:
            raise NotSupportedError("BaseEventSourcedAggregate cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        return [
            ("auto_add_id_field", True),
            ("stream_name", inflection.underscore(cls.__name__)),
            ("aggregate_cluster", None),
        ]

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        # Associate a `_projections` map with subclasses.
        #   It needs to be initialized here because if it
        #   were initialized in __init__, the same collection object
        #   would be made available across all subclasses,
        #   defeating its purpose.
        setattr(subclass, "_projections", defaultdict(set))

        # Store associated events
        setattr(subclass, "_events_cls_map", {})

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

    def _apply(self, event: BaseEvent) -> None:
        """Apply the event onto the aggregate by calling the appropriate projection.

        Args:
            event (BaseEvent): Event object to apply
        """
        # FIXME Handle case of missing projection
        event_name = fully_qualified_name(event.__class__)

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
    def from_events(cls, events: List[BaseEvent]) -> "BaseEventSourcedAggregate":
        """Reconstruct an aggregate from a list of events."""
        # Initialize the aggregate with the first event's payload and apply it
        aggregate = cls(**events[0].payload)
        aggregate._apply(events[0])

        # Apply the rest of the events
        for event in events[1:]:
            aggregate._apply(event)

        return aggregate


def apply(fn):
    """Decorator to mark methods in EventHandler classes."""

    if len(typing.get_type_hints(fn)) > 2:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Handler method `{fn.__name__}` has incorrect number of arguments"
                ]
            }
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
            {
                "_entity": [
                    f"Apply method `{fn.__name__}` should accept an argument annotated with the Event class"
                ]
            }
        )

    @functools.wraps(fn)
    def wrapper(*args):
        fn(*args)

    setattr(wrapper, "_event_cls", _event_cls)

    return wrapper


def event_sourced_aggregate_factory(element_cls, **opts):
    element_cls = derive_element_class(element_cls, BaseEventSourcedAggregate, **opts)

    # Iterate through methods marked as `@apply` and construct a projections map
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_event_cls"):
            element_cls._projections[fully_qualified_name(method._event_cls)].add(
                method
            )
            element_cls._events_cls_map[fully_qualified_name(method._event_cls)] = (
                method._event_cls
            )

            # Associate Event with the aggregate class
            #
            # This can potentially cause a problem because an Event can only be associated
            #   with one aggregate class, but multiple event handlers can consume it.
            #   By resetting the event's aggregate class, its previous association is lost.
            #   We catch this problem during domain validation.
            #
            #   The domain validation should check for the same event class being present
            #   in `_events_cls_map` of multiple aggregate classes.
            method._event_cls.meta_.part_of = element_cls

    return element_cls
