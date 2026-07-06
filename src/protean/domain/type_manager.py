"""Event/command type management extracted from the Domain class.

The ``TypeManager`` owns the ``_events_and_commands`` type registry,
upcaster chain management, fact event generation, and external event
registration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from protean.core.aggregate import element_to_fact_event
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects
from protean.utils.upcasting import UpcasterChain, upcaster_event_name

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class TypeManager:
    """Manage event/command type strings, upcaster chains, and fact events.

    Instantiated once by ``Domain.__init__()`` and called during
    ``Domain.init()`` to assign type strings and build upcaster chains.

    Owns the following state (previously on Domain):
    - ``events_and_commands`` — maps type strings to event/command classes
    - ``upcasters`` — registered upcaster classes, read from the domain registry
    - ``upcaster_chain`` — the built upcaster chain for schema evolution
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain
        self.events_and_commands: dict[str, type[BaseCommand] | type[BaseEvent]] = {}
        self.upcaster_chain: UpcasterChain = UpcasterChain()

    @property
    def upcasters(self) -> list[type[BaseUpcaster]]:
        """Registered upcaster classes, sourced from the domain registry.

        Upcasters register through the standard element lifecycle (see #1109),
        so the registry is the single source of truth rather than a separate
        list on this manager.
        """
        registry = self._domain._domain_registry
        return [
            cast(type[BaseUpcaster], record.cls)
            for record in registry._elements[DomainObjects.UPCASTER.value].values()
        ]

    def set_and_record_types(self) -> None:
        """Set ``__type__`` on all registered events and commands.

        Type format: ``DomainName.ClassName.version``
        E.g. ``Authentication.UserRegistered.v1``
        """
        registry = self._domain._domain_registry
        for element_type in [DomainObjects.EVENT, DomainObjects.COMMAND]:
            for _, element in registry._elements[element_type.value].items():
                type_string = (
                    f"{self._domain.camel_case_name}."
                    f"{element.cls.__name__}."
                    f"v{element.cls.__version__}"
                )

                setattr(element.cls, "__type__", type_string)
                self.events_and_commands[type_string] = element.cls

    def _populate_chain(self, chain: UpcasterChain) -> None:
        """Register every upcaster as an edge on ``chain`` and build it.

        ``build_chains`` raises ``ConfigurationError`` on a malformed chain
        (duplicate / cyclic / non-convergent). Requires ``set_and_record_types``
        to have run so event type strings are available.
        """
        for upcaster_cls in self.upcasters:
            # event_type may be an Event class or a string (forward reference).
            # Resolve by name: build_chains validates the named event is
            # registered (raising an unreachable-terminal ConfigurationError if
            # not), so a valid string works and a bad one fails cleanly.
            event_name = upcaster_event_name(upcaster_cls.meta_.event_type)
            event_base_type = f"{self._domain.camel_case_name}.{event_name}"

            chain.register_upcaster(
                event_base_type=event_base_type,
                from_version=upcaster_cls.meta_.from_version,
                to_version=upcaster_cls.meta_.to_version,
                upcaster_cls=upcaster_cls,
            )

        chain.build_chains(self.events_and_commands)

    def build_upcaster_chains(self) -> None:
        """Build the runtime upcaster chain used during deserialization.

        Called during ``init()`` after ``set_and_record_types()``. Rebuilt from
        scratch each call so it is idempotent and never carries stale edges from
        a prior (possibly failed) build.
        """
        self.upcaster_chain = UpcasterChain()
        self._populate_chain(self.upcaster_chain)

    def validate_upcaster_chains(self) -> None:
        """Validate the upcaster chains without touching the runtime chain.

        Builds a throwaway chain so ``check()`` can surface a malformed chain as
        a structured error without mutating deserialization state (the validator
        stays read-only w.r.t. runtime state).
        """
        self._populate_chain(UpcasterChain())

    def register_external_event(
        self, event_cls: type[BaseEvent], type_string: str
    ) -> None:
        """Register an external event with the domain.

        Maps an external event type string to an event class without
        adding it to the domain registry.
        """
        if (
            not issubclass(event_cls, BaseEvent)
            or event_cls.element_type != DomainObjects.EVENT
        ):
            raise IncorrectUsageError(f"Class `{event_cls.__name__}` is not an Event")

        self.events_and_commands[type_string] = event_cls
        setattr(event_cls, "__type__", type_string)

    def generate_fact_event_classes(self) -> None:
        """Generate FactEvent classes for all aggregates with ``fact_events`` enabled."""
        registry = self._domain._domain_registry
        for _, element in registry._elements[DomainObjects.AGGREGATE.value].items():
            if element.cls.meta_.fact_events:
                event_cls = element_to_fact_event(element.cls)
                self._domain.register(
                    event_cls,
                    auto_generated=True,
                    part_of=element.cls,
                    is_fact_event=True,
                )
