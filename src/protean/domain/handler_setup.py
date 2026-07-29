"""Handler setup logic extracted from the Domain class.

The ``HandlerConfigurator`` discovers methods decorated with ``@handle``,
``@read``, etc. on registered handler classes, validates their targets,
and populates each handler class's ``_handlers`` map so the runtime can
dispatch commands, events, and queries to the correct method.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, cast

from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.process_manager import _generate_pm_transition_event
from protean.core.query import BaseQuery
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects

if TYPE_CHECKING:
    from protean.core.process_manager import BaseProcessManager
    from protean.domain import Domain
    from protean.utils.container import OptionsMixin


logger = logging.getLogger(__name__)


class HandlerMethod(Protocol):
    """Structural type for a method decorated with ``@handle`` / ``@read``.

    The decorators in ``protean.utils.mixins`` attach ``_target_cls`` (and, for
    ``@handle``, ``_start`` / ``_correlate`` / ``_end``) to the wrapped method
    via ``setattr``. ``_target_cls`` holds the target command/event/query class,
    or the ``"$any"`` sentinel string for wildcard event handlers (matched by an
    ``== "$any"`` comparison, and guarded by ``inspect.isclass`` before any
    class-only attribute access).
    """

    _target_cls: type[Any] | str

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


def _is_handler_method(method_name: str, method: object) -> bool:
    """Return True if *method* is a user-defined handler (has ``_target_cls``)."""
    return not (
        method_name.startswith("__") and method_name.endswith("__")
    ) and hasattr(method, "_target_cls")


def _discover_handler_methods(cls: type) -> list[tuple[str, HandlerMethod]]:
    """Return all handler-decorated methods on *cls*."""
    # ``getmembers`` yields concrete function/method types; ``_is_handler_method``
    # verifies each carries the dynamically-attached ``_target_cls`` at runtime,
    # so each match structurally satisfies ``HandlerMethod``.
    return [
        (name, cast("HandlerMethod", method))
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
        for element in registry._elements[DomainObjects.COMMAND_HANDLER.value].values():
            if element.cls._handlers:  # Protect against re-registration
                continue

            for method_name, method in _discover_handler_methods(element.cls):
                target_cls = self._validate_command_handler_method(
                    method_name, method, element.cls
                )

                command_type = (
                    target_cls.__type__
                    if issubclass(target_cls, BaseCommand)
                    else target_cls
                )

                # Do not allow multiple handlers per command
                if (
                    command_type in element.cls._handlers
                    and len(element.cls._handlers[command_type]) != 0
                ):
                    raise NotSupportedError(
                        f"Command {target_cls.__name__} cannot be handled by multiple handlers"
                    )

                element.cls._handlers[command_type].add(method)

    @staticmethod
    def _validate_command_handler_method(
        method_name: str, method: HandlerMethod, handler_cls: type[OptionsMixin]
    ) -> type[BaseCommand]:
        """Validate a single command handler method's target and return it."""
        target_cls = method._target_cls
        if not inspect.isclass(target_cls) or not issubclass(target_cls, BaseCommand):
            raise IncorrectUsageError(
                f"Method `{method_name}` in Command Handler `{handler_cls.__name__}` "
                "is not associated with a command"
            )

        if not target_cls.meta_.part_of:
            raise IncorrectUsageError(
                f"Command `{target_cls.__name__}` in Command Handler `{handler_cls.__name__}` "
                "is not associated with an aggregate"
            )

        if target_cls.meta_.part_of != handler_cls.meta_.part_of:
            raise IncorrectUsageError(
                f"Command `{target_cls.__name__}` in Command Handler `{handler_cls.__name__}` "
                "is not associated with the same aggregate as the Command Handler"
            )

        return target_cls

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
        for element in registry._elements[DomainObjects.EVENT_HANDLER.value].values():
            for _method_name, method in _discover_handler_methods(element.cls):
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
        for element in registry._elements[DomainObjects.PROJECTOR.value].values():
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
        registry = self._domain._domain_registry
        for element in registry._elements[DomainObjects.PROCESS_MANAGER.value].values():
            pm_cls = element.cls

            # Build handler map
            if not pm_cls._handlers:  # Protect against re-registration
                self._wire_process_manager_handlers(pm_cls)

            # Generate and register transition event
            self._register_transition_event(pm_cls, _generate_pm_transition_event)

            # Infer stream categories if not explicitly set
            if not pm_cls.meta_.stream_categories:
                self._infer_stream_categories(pm_cls)

    def _wire_process_manager_handlers(self, pm_cls: type[BaseProcessManager]) -> None:
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

    def _register_transition_event(
        self,
        pm_cls: type[BaseProcessManager],
        generator_fn: Callable[[type[BaseProcessManager]], type[BaseEvent]],
    ) -> None:
        """Generate, register, and type-tag the transition event for a process manager."""
        transition_cls = generator_fn(pm_cls)

        # Register transition event with domain
        self._domain._register_element(
            DomainObjects.EVENT,
            transition_cls,
            internal=True,
            auto_generated=True,
            part_of=pm_cls,
        )

        # Set __type__ on the transition event
        type_string = (
            f"{self._domain.camel_case_name}."
            f"{transition_cls.__name__}."
            f"v{getattr(transition_cls, '__version__', 1)}"
        )
        transition_cls.__type__ = type_string
        self._domain._events_and_commands[type_string] = transition_cls

        # Store transition event class on PM
        pm_cls._transition_event_cls = transition_cls

    @staticmethod
    def _infer_stream_categories(pm_cls: type[BaseProcessManager]) -> None:
        """Infer stream categories from the aggregates of handled events."""
        inferred_categories: set[str] = set()
        for _, method in _discover_handler_methods(pm_cls):
            if inspect.isclass(method._target_cls):
                target: type[Any] = method._target_cls
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
        for element in registry._elements[DomainObjects.QUERY.value].values():
            type_string = f"{self._domain.camel_case_name}.{element.cls.__name__}"
            element.cls.__type__ = type_string

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
        for element in registry._elements[DomainObjects.QUERY_HANDLER.value].values():
            if element.cls._handlers:  # Protect against re-registration
                continue

            for method_name, method in _discover_handler_methods(element.cls):
                target_cls = self._validate_query_handler_method(
                    method_name, method, element.cls
                )

                query_type = target_cls.__type__

                # Do not allow multiple handlers per query
                if (
                    query_type in element.cls._handlers
                    and len(element.cls._handlers[query_type]) != 0
                ):
                    raise NotSupportedError(
                        f"Query {target_cls.__name__} cannot be handled "
                        f"by multiple handlers"
                    )

                element.cls._handlers[query_type].add(method)

    # ------------------------------------------------------------------
    # Partition keys (sequential_by, ADR-0028)
    # ------------------------------------------------------------------

    def validate_sequential_by(self) -> None:
        """Validate ``sequential_by`` handlers and build the partition-key map.

        Runs during ``_prepare()`` (needs no broker, so it also runs under
        ``check()``). Enforces two of ADR-0028's registration rules and records
        the result on the domain:

        - **Field existence** — every event/command type a ``sequential_by``
          handler handles must declare the named field (for a process manager,
          the field its ``correlate`` spec resolves for that event).
        - **One key per category** — a stream category can be partitioned by at
          most one key; two handlers asking for different keys on the same
          category is an error.

        The resulting ``stream_category -> partition_key`` map is stored on
        ``domain._partition_keys`` for the Unit of Work to read at commit. The
        third rule (broker capability gating) needs an initialized broker and
        runs later, in :meth:`validate_sequential_by_capabilities`.
        """
        registry = self._domain._domain_registry
        # Rebuild from scratch so a re-run (re-init) does not accumulate stale
        # entries; ``declared_by`` tracks the first declarer for conflict text.
        partition_map: dict[str, str] = {}
        declared_by: dict[str, str] = {}

        def _record(category: str, field: str, element_name: str) -> None:
            existing = partition_map.get(category)
            if existing is not None and existing != field:
                raise IncorrectUsageError(
                    f"Stream category `{category}` is partitioned by conflicting "
                    f"keys: `{existing}` (from `{declared_by[category]}`) and "
                    f"`{field}` (from `{element_name}`). A category can be "
                    f"partitioned by only one key (ADR-0028)."
                )
            partition_map[category] = field
            declared_by.setdefault(category, element_name)

        # Event handlers: value is a direct field name on each handled event.
        for element in registry._elements[DomainObjects.EVENT_HANDLER.value].values():
            handler_cls = element.cls
            key = getattr(handler_cls.meta_, "sequential_by", None)
            if not key:
                continue
            for _, method in _discover_handler_methods(handler_cls):
                target = method._target_cls
                if inspect.isclass(target) and issubclass(target, BaseEvent):
                    self._assert_partition_field(target, key, handler_cls, "Event")
                    category = self._event_published_category(target)
                    if category is not None:
                        _record(category, key, handler_cls.__name__)

        # Command handlers: value is a direct field name on each handled command.
        for element in registry._elements[DomainObjects.COMMAND_HANDLER.value].values():
            handler_cls = element.cls
            key = getattr(handler_cls.meta_, "sequential_by", None)
            if not key:
                continue
            for _, method in _discover_handler_methods(handler_cls):
                target = method._target_cls
                if inspect.isclass(target) and issubclass(target, BaseCommand):
                    self._assert_partition_field(target, key, handler_cls, "Command")
            _record(handler_cls.meta_.stream_category, key, handler_cls.__name__)

        # Process managers: boolean opt-in; the per-category key is the field the
        # event's ``correlate`` spec maps to the correlation value.
        for element in registry._elements[DomainObjects.PROCESS_MANAGER.value].values():
            pm_cls = element.cls
            if not getattr(pm_cls.meta_, "sequential_by", None):
                continue
            for _, method in _discover_handler_methods(pm_cls):
                target = method._target_cls
                # Defensive: ``_setup_process_managers`` (run earlier in
                # ``_prepare``) already rejects a PM handler whose target is not
                # an event and one with no ``correlate``, so neither guard below
                # can fire through init. They stay as belt-and-suspenders against
                # a future reordering, hence the coverage pragmas.
                if not (inspect.isclass(target) and issubclass(target, BaseEvent)):
                    continue  # pragma: no cover
                field = self._correlate_field(getattr(method, "_correlate", None))
                if field is None:  # pragma: no cover
                    raise IncorrectUsageError(
                        f"Process Manager `{pm_cls.__name__}` sets "
                        f"`sequential_by=True` but handler for "
                        f"`{target.__name__}` has no usable `correlate` field "
                        f"to partition by (ADR-0028)."
                    )
                self._assert_partition_field(target, field, pm_cls, "Event")
                category = self._event_published_category(target)
                if category is not None:
                    _record(category, field, pm_cls.__name__)

        self._domain._partition_keys = partition_map

    def validate_sequential_by_capabilities(self) -> None:
        """Gate ``sequential_by`` handlers on the broker's partitioning support.

        ADR-0028 decision 8: a ``sequential_by`` handler is rejected at
        registration when its target broker does not advertise
        ``STREAM_PARTITIONING``. The single-threaded inline broker is the
        no-op exception — it processes messages in submission order, so
        ``sequential_by`` is already satisfied there and is accepted.

        Runs from ``Domain.init()`` after adapters are initialized (it needs a
        live broker), so ``check()`` — which does not initialize adapters —
        skips it.
        """
        from protean.adapters.broker.inline import InlineBroker  # noqa: PLC0415
        from protean.port.broker import BrokerCapabilities  # noqa: PLC0415

        if not self._domain._partition_keys:
            return

        # The partition segment is applied where the outbox publishes, so the
        # broker that must support partitioning is the internal outbox broker
        # (default ``"default"``, which is also the broker handlers consume
        # from). Fall back to the default broker if it is named differently.
        broker_name = self._domain.config.get("outbox", {}).get("broker", "default")
        broker = self._domain.brokers.get(broker_name) or self._domain.brokers.get(
            "default"
        )
        if broker is None:
            return

        if isinstance(broker, InlineBroker):
            return
        if broker.has_capability(BrokerCapabilities.STREAM_PARTITIONING):
            return

        categories = ", ".join(sorted(self._domain._partition_keys))
        raise IncorrectUsageError(
            f"Broker `{broker.name}` does not advertise STREAM_PARTITIONING, "
            f"which `sequential_by` requires. Offending categories: "
            f"{categories} (ADR-0028)."
        )

    @staticmethod
    def _assert_partition_field(
        target_cls: type[Any], field_name: str, element_cls: type[Any], kind: str
    ) -> None:
        """Raise if *target_cls* has no field named *field_name*."""
        from protean.utils.reflection import fields  # noqa: PLC0415

        if field_name not in fields(target_cls):
            raise IncorrectUsageError(
                f"`{element_cls.__name__}` declares "
                f"`sequential_by='{field_name}'` but {kind} "
                f"`{target_cls.__name__}` has no field named `{field_name}` "
                f"(ADR-0028)."
            )

    @staticmethod
    def _event_published_category(event_cls: type[Any]) -> str | None:
        """Return the stream category an event is published to (its aggregate's).

        Matches the category the Unit of Work reads off the event at commit, so
        the map keys line up with the extraction lookup.
        """
        part_of = getattr(event_cls.meta_, "part_of", None)
        if part_of is not None and not isinstance(part_of, str):
            meta = getattr(part_of, "meta_", None)
            if meta is not None:
                return cast("str | None", getattr(meta, "stream_category", None))
        return None

    @staticmethod
    def _correlate_field(correlate_spec: str | dict[str, str] | None) -> str | None:
        """Resolve the event field name from a process manager's correlate spec.

        A string spec names the field directly; a ``{pm_field: event_field}``
        dict partitions by the event field it maps from.
        """
        if isinstance(correlate_spec, str):
            return correlate_spec
        if isinstance(correlate_spec, dict) and correlate_spec:
            return next(iter(correlate_spec.values()))
        return None

    @staticmethod
    def _validate_query_handler_method(
        method_name: str, method: HandlerMethod, handler_cls: type[OptionsMixin]
    ) -> type[BaseQuery]:
        """Validate a single query handler method's target and return it."""
        if hasattr(method, "_start"):
            raise IncorrectUsageError(
                f"Method `{method_name}` in Query Handler "
                f"`{handler_cls.__name__}` is decorated with `@handle`, which "
                f"wraps execution in a UnitOfWork. Query Handler methods must "
                f"be stateless reads — use `@read` to handle a query here, or "
                f"move this method to a Command or Event Handler if it handles "
                f"a command or event"
            )

        target_cls = method._target_cls
        if not inspect.isclass(target_cls) or not issubclass(target_cls, BaseQuery):
            raise IncorrectUsageError(
                f"Method `{method_name}` in Query Handler "
                f"`{handler_cls.__name__}` is not associated with a query"
            )

        if not target_cls.meta_.part_of:
            raise IncorrectUsageError(
                f"Query `{target_cls.__name__}` in Query Handler "
                f"`{handler_cls.__name__}` is not associated with a projection"
            )

        if target_cls.meta_.part_of != handler_cls.meta_.part_of:
            raise IncorrectUsageError(
                f"Query `{target_cls.__name__}` in Query Handler "
                f"`{handler_cls.__name__}` is not associated with the same "
                f"projection as the Query Handler"
            )

        return target_cls
