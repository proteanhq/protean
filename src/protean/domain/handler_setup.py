"""Handler setup logic extracted from the Domain class.

The ``HandlerConfigurator`` discovers methods decorated with ``@handle``,
``@read``, etc. on registered handler classes, validates their targets,
and populates each handler class's ``_handlers`` map so the runtime can
dispatch commands, events, and queries to the correct method.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING

from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


def _is_handler_method(method_name: str, method: object) -> bool:
    """Return True if *method* is a user-defined handler (has ``_target_cls``)."""
    return not (
        method_name.startswith("__") and method_name.endswith("__")
    ) and hasattr(method, "_target_cls")


def _discover_handler_methods(cls: type) -> list[tuple[str, object]]:
    """Return all handler-decorated methods on *cls*."""
    return [
        (name, method)
        for name, method in inspect.getmembers(cls, predicate=inspect.isroutine)
        if _is_handler_method(name, method)
    ]


class HandlerConfigurator:
    """Configure handler maps for command handlers, event handlers,
    projectors, process managers, and query handlers.

    Instantiated once by ``Domain.__init__()`` and called during
    ``Domain.init()`` to wire all handler methods.
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain

    # ------------------------------------------------------------------
    # Command Handlers
    # ------------------------------------------------------------------

    def setup_command_handlers(self) -> None:
        """Discover ``@handle``-decorated methods in command handlers and
        build the handler map.

        Validates:
        - Target is a ``BaseCommand`` subclass
        - Target command is associated with an aggregate
        - Command's aggregate matches the handler's aggregate
        - No duplicate handlers for the same command
        """
        registry = self._domain._domain_registry
        for _, element in registry._elements[
            DomainObjects.COMMAND_HANDLER.value
        ].items():
            if element.cls._handlers:  # Protect against re-registration
                continue

            for method_name, method in _discover_handler_methods(element.cls):
                self._validate_command_handler_method(method_name, method, element.cls)

                command_type = (
                    method._target_cls.__type__
                    if issubclass(method._target_cls, BaseCommand)
                    else method._target_cls
                )

                # Do not allow multiple handlers per command
                if (
                    command_type in element.cls._handlers
                    and len(element.cls._handlers[command_type]) != 0
                ):
                    raise NotSupportedError(
                        f"Command {method._target_cls.__name__} cannot be handled by multiple handlers"
                    )

                element.cls._handlers[command_type].add(method)

    @staticmethod
    def _validate_command_handler_method(
        method_name: str, method: object, handler_cls: type
    ) -> None:
        """Validate a single command handler method's target."""
        if not inspect.isclass(method._target_cls) or not issubclass(
            method._target_cls, BaseCommand
        ):
            raise IncorrectUsageError(
                f"Method `{method_name}` in Command Handler `{handler_cls.__name__}` "
                "is not associated with a command"
            )

        if not method._target_cls.meta_.part_of:
            raise IncorrectUsageError(
                f"Command `{method._target_cls.__name__}` in Command Handler `{handler_cls.__name__}` "
                "is not associated with an aggregate"
            )

        if method._target_cls.meta_.part_of != handler_cls.meta_.part_of:
            raise IncorrectUsageError(
                f"Command `{method._target_cls.__name__}` in Command Handler `{handler_cls.__name__}` "
                "is not associated with the same aggregate as the Command Handler"
            )

    # ------------------------------------------------------------------
    # Event Handlers
    # ------------------------------------------------------------------

    def setup_event_handlers(self) -> None:
        """Discover ``@handle``-decorated methods in event handlers and
        build the handler map.

        Supports both typed events and the ``$any`` wildcard target.
        Multiple handlers per event type are allowed.
        """
        registry = self._domain._domain_registry
        for _, element in registry._elements[DomainObjects.EVENT_HANDLER.value].items():
            for method_name, method in _discover_handler_methods(element.cls):
                if method._target_cls == "$any":
                    # Only one $any handler per event handler class
                    element.cls._handlers["$any"] = {method}
                else:
                    event_type = (
                        method._target_cls.__type__
                        if inspect.isclass(method._target_cls)
                        and issubclass(method._target_cls, BaseEvent)
                        else method._target_cls
                    )
                    element.cls._handlers[event_type].add(method)

    # ------------------------------------------------------------------
    # Projectors
    # ------------------------------------------------------------------

    def setup_projectors(self) -> None:
        """Discover ``@handle``-decorated methods in projectors and build
        the handler map.

        Validates that each handler method targets an event class.
        """
        registry = self._domain._domain_registry
        for _, element in registry._elements[DomainObjects.PROJECTOR.value].items():
            if element.cls._handlers:  # Protect against re-registration
                continue

            for method_name, method in _discover_handler_methods(element.cls):
                if not inspect.isclass(method._target_cls) or not issubclass(
                    method._target_cls, BaseEvent
                ):
                    raise IncorrectUsageError(
                        f"Projector method `{method_name}` in `{element.cls.__name__}` "
                        "is not associated with an event"
                    )

                event_type = (
                    method._target_cls.__type__
                    if issubclass(method._target_cls, BaseEvent)
                    else method._target_cls
                )

                element.cls._handlers[event_type].add(method)

    # ------------------------------------------------------------------
    # Process Managers
    # ------------------------------------------------------------------

    def setup_process_managers(self) -> None:
        """Discover ``@handle``-decorated methods in process managers,
        validate them, generate transition events, and infer stream categories.
        """
        from protean.core.process_manager import _generate_pm_transition_event

        registry = self._domain._domain_registry
        for _, element in registry._elements[
            DomainObjects.PROCESS_MANAGER.value
        ].items():
            pm_cls = element.cls

            # Build handler map
            if not pm_cls._handlers:  # Protect against re-registration
                self._wire_process_manager_handlers(pm_cls)

            # Generate and register transition event
            self._register_transition_event(pm_cls, _generate_pm_transition_event)

            # Infer stream categories if not explicitly set
            if not pm_cls.meta_.stream_categories:
                self._infer_stream_categories(pm_cls)

    def _wire_process_manager_handlers(self, pm_cls: type) -> None:
        """Wire handler methods for a single process manager class."""
        has_start = False

        for method_name, method in _discover_handler_methods(pm_cls):
            if not inspect.isclass(method._target_cls) or not issubclass(
                method._target_cls, BaseEvent
            ):
                raise IncorrectUsageError(
                    f"Process Manager method `{method_name}` in `{pm_cls.__name__}` "
                    "is not associated with an event"
                )

            if not getattr(method, "_correlate", None):
                raise IncorrectUsageError(
                    f"Handler `{method_name}` in Process Manager "
                    f"`{pm_cls.__name__}` must specify a `correlate` parameter"
                )

            if getattr(method, "_start", False):
                has_start = True

            event_type = (
                method._target_cls.__type__
                if issubclass(method._target_cls, BaseEvent)
                else method._target_cls
            )

            pm_cls._handlers[event_type].add(method)

        if not has_start:
            raise IncorrectUsageError(
                f"Process Manager `{pm_cls.__name__}` must have at least "
                f"one handler with `start=True`"
            )

    def _register_transition_event(self, pm_cls: type, generator_fn: callable) -> None:
        """Generate, register, and type-tag the transition event for a process manager."""
        transition_cls = generator_fn(pm_cls)

        # Register transition event with domain
        self._domain._register_element(
            DomainObjects.EVENT,
            transition_cls,
            internal=True,
            part_of=pm_cls,
        )

        # Set __type__ on the transition event
        type_string = (
            f"{self._domain.camel_case_name}."
            f"{transition_cls.__name__}."
            f"{getattr(transition_cls, '__version__', 'v1')}"
        )
        setattr(transition_cls, "__type__", type_string)
        self._domain._events_and_commands[type_string] = transition_cls

        # Store transition event class on PM
        pm_cls._transition_event_cls = transition_cls

    @staticmethod
    def _infer_stream_categories(pm_cls: type) -> None:
        """Infer stream categories from the aggregates of handled events."""
        inferred_categories: set[str] = set()
        for _, method in _discover_handler_methods(pm_cls):
            if inspect.isclass(method._target_cls):
                target = method._target_cls
                if hasattr(target, "meta_") and hasattr(target.meta_, "part_of"):
                    part_of = target.meta_.part_of
                    if part_of and hasattr(part_of, "meta_"):
                        inferred_categories.add(part_of.meta_.stream_category)

        pm_cls.meta_.stream_categories = list(inferred_categories)

    # ------------------------------------------------------------------
    # Query Types & Query Handlers
    # ------------------------------------------------------------------

    def set_query_type(self) -> None:
        """Set ``__type__`` on registered queries for handler routing."""
        registry = self._domain._domain_registry
        for _, element in registry._elements[DomainObjects.QUERY.value].items():
            type_string = f"{self._domain.camel_case_name}.{element.cls.__name__}"
            setattr(element.cls, "__type__", type_string)

    def setup_query_handlers(self) -> None:
        """Discover ``@read``-decorated methods in query handlers and build
        the handler map.

        Validates:
        - Target is a ``BaseQuery`` subclass
        - Target query is associated with a projection
        - Query's projection matches the handler's projection
        - No duplicate handlers for the same query
        """

        registry = self._domain._domain_registry
        for _, element in registry._elements[DomainObjects.QUERY_HANDLER.value].items():
            if element.cls._handlers:  # Protect against re-registration
                continue

            for method_name, method in _discover_handler_methods(element.cls):
                self._validate_query_handler_method(method_name, method, element.cls)

                query_type = method._target_cls.__type__

                # Do not allow multiple handlers per query
                if (
                    query_type in element.cls._handlers
                    and len(element.cls._handlers[query_type]) != 0
                ):
                    raise NotSupportedError(
                        f"Query {method._target_cls.__name__} cannot be handled "
                        f"by multiple handlers"
                    )

                element.cls._handlers[query_type].add(method)

    @staticmethod
    def _validate_query_handler_method(
        method_name: str, method: object, handler_cls: type
    ) -> None:
        """Validate a single query handler method's target."""
        from protean.core.query import BaseQuery

        if not inspect.isclass(method._target_cls) or not issubclass(
            method._target_cls, BaseQuery
        ):
            raise IncorrectUsageError(
                f"Method `{method_name}` in Query Handler "
                f"`{handler_cls.__name__}` is not associated with a query"
            )

        if not method._target_cls.meta_.part_of:
            raise IncorrectUsageError(
                f"Query `{method._target_cls.__name__}` in Query Handler "
                f"`{handler_cls.__name__}` is not associated with a projection"
            )

        if method._target_cls.meta_.part_of != handler_cls.meta_.part_of:
            raise IncorrectUsageError(
                f"Query `{method._target_cls.__name__}` in Query Handler "
                f"`{handler_cls.__name__}` is not associated with the same "
                f"projection as the Query Handler"
            )
