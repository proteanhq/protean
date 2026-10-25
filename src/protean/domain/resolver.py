"""Element resolution logic extracted from the Domain class.

The ``ElementResolver`` resolves string-based references between domain
elements (e.g. ``HasMany("Comment")`` → actual ``Comment`` class) and
assigns aggregate clusters so that entities, events, and commands know
which aggregate root they belong to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from protean.core.aggregate import BaseAggregate
from protean.core.command_handler import derive_command_stream_category
from protean.core.database_model import check_database_model_fields
from protean.core.event_sourced_repository import check_event_sourced_part_of
from protean.core.process_manager import BaseProcessManager
from protean.exceptions import ConfigurationError, NotSupportedError
from protean.utils import PART_OF_KINDS, DomainObjects, _check_part_of_kind

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class ElementResolver:
    """Resolves string references in domain elements and assigns aggregate clusters.

    Instantiated once by ``Domain.__init__()`` and called during
    ``Domain.init()`` to resolve pending references and build the
    aggregate cluster graph.
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain

    def resolve_references(self) -> None:
        """Resolve pending class references in association fields.

        References that cannot be resolved (target not registered) are left
        in ``_pending_class_resolutions`` so that ``DomainValidator`` can
        report them with contextual error messages. Only the failed entries
        stay: one name can be the target of several references, and those
        that resolved must not be reported.
        """
        pending = self._domain._pending_class_resolutions
        for name in list(pending.keys()):
            unresolved: list[Any] = []
            # An entity's ``part_of`` is resolved and checked before its
            # reference field, which cannot point at an owner without an
            # identity field.
            entries = sorted(pending[name], key=lambda e: e[0] != "AggregateCls")
            for entry in entries:
                resolution_type, params = entry
                try:
                    match resolution_type:
                        case "Association":
                            field_obj, owner_cls = params
                            to_cls = self._domain.fetch_element_cls_from_registry(
                                field_obj.to_cls,
                                (
                                    DomainObjects.AGGREGATE,
                                    DomainObjects.ENTITY,
                                ),
                            )
                            field_obj._resolve_to_cls(self._domain, to_cls, owner_cls)
                        case "ValueObject":
                            field_obj, owner_cls = params
                            to_cls = self._domain.fetch_element_cls_from_registry(
                                field_obj.value_object_cls,
                                (DomainObjects.VALUE_OBJECT,),
                            )
                            field_obj._resolve_to_cls(self._domain, to_cls, owner_cls)
                        case "AggregateCls":
                            cls = params
                            to_cls = self._resolve_part_of(cls)
                            cls.meta_.part_of = to_cls
                            _check_part_of_kind(cls)
                            self._finalize_aggregate_link(cls, to_cls)
                        case "ProjectionCls":
                            cls = params
                            to_cls = self._domain.fetch_element_cls_from_registry(
                                cls.meta_.projector_for,
                                (DomainObjects.PROJECTION,),
                            )
                            cls.meta_.projector_for = to_cls
                        case "QueryProjectionCls":
                            cls = params
                            to_cls = self._domain.fetch_element_cls_from_registry(
                                cls.meta_.part_of,
                                (DomainObjects.PROJECTION,),
                            )
                            cls.meta_.part_of = to_cls
                        case "QueryHandlerProjectionCls":
                            cls = params
                            to_cls = self._domain.fetch_element_cls_from_registry(
                                cls.meta_.part_of,
                                (DomainObjects.PROJECTION,),
                            )
                            cls.meta_.part_of = to_cls
                        case _:
                            raise NotSupportedError(
                                f"Resolution Type {resolution_type} not supported"
                            )
                except ConfigurationError:
                    # Target not found in registry — leave in pending list
                    # so DomainValidator can report it with context.
                    unresolved.append(entry)

            if unresolved:
                pending[name] = unresolved
            else:
                del pending[name]

    def _resolve_part_of(self, cls: Any) -> Any:
        """Resolve a string ``part_of`` against the kinds the element allows.

        Each kind is tried on its own, aggregate first. A name shared by an
        aggregate and an entity or process manager then still resolves to the
        aggregate, and the search never fails as ambiguous across two kinds.
        The search moves to the next kind only when no element of the current
        kind carries the name. A name that is ambiguous within one kind fails
        instead of quietly binding to an element of a later kind.
        """
        name = cls.meta_.part_of
        *preferred, last = PART_OF_KINDS[cls.element_type]
        for kind in preferred:
            if self._has_element_named(name, kind):
                return self._domain.fetch_element_cls_from_registry(name, (kind,))
        return self._domain.fetch_element_cls_from_registry(name, (last,))

    def _has_element_named(self, name: str, kind: DomainObjects) -> bool:
        registry = self._domain._domain_registry
        return name in registry._elements[kind.value] or any(
            record.class_type == kind.value
            for record in registry._elements_by_name.get(name, [])
        )

    def _finalize_aggregate_link(self, cls: Any, aggregate_cls: Any) -> None:
        """Complete element wiring deferred when ``part_of`` was a string.

        Command and event handler factories derive their ``stream_category``
        from the associated aggregate, and the event-sourced repository factory
        checks that the aggregate is event sourced. A database model's fields
        are checked against its target, and the model is filed under it; that
        target can be an aggregate, an entity or a projection. When
        ``part_of`` is given as a string reference, that work is skipped at
        registration (the target is not yet resolved) and completed here, once
        the reference points at a real class. Class-reference ``part_of`` is
        finalized eagerly at registration and never reaches this path.
        """
        element_type = cls.element_type
        if element_type == DomainObjects.COMMAND_HANDLER:
            cls.meta_.stream_category = derive_command_stream_category(aggregate_cls)
        # Respect an explicitly configured stream_category; only derive
        # when the handler relied on its aggregate for the value.
        elif (
            element_type == DomainObjects.EVENT_HANDLER
            and cls.meta_.stream_category is None
        ):
            cls.meta_.stream_category = aggregate_cls.meta_.stream_category
        elif element_type == DomainObjects.EVENT_SOURCED_REPOSITORY:
            check_event_sourced_part_of(cls)
        elif element_type == DomainObjects.DATABASE_MODEL:
            check_database_model_fields(cls)
            self._domain._file_database_model(cls)

    def assign_aggregate_clusters(self) -> None:
        """Assign aggregate clusters to all relevant elements."""
        registry = self._domain._domain_registry

        # Assign Aggregates and Process Managers to their own cluster
        for element_type in [DomainObjects.AGGREGATE, DomainObjects.PROCESS_MANAGER]:
            for element in registry._elements[element_type.value].values():
                element.cls.meta_.aggregate_cluster = element.cls

        # Derive root aggregate for other elements
        for element_type in [
            DomainObjects.ENTITY,
            DomainObjects.EVENT,
            DomainObjects.COMMAND,
        ]:
            for element in registry._elements[element_type.value].values():
                part_of = element.cls.meta_.part_of
                if part_of:
                    # Traverse up the graph tree to find the root aggregate
                    chain = [element.cls]
                    while not issubclass(part_of, BaseAggregate) and not issubclass(
                        part_of, BaseProcessManager
                    ):
                        if part_of in chain:
                            names = " -> ".join(
                                f"`{c.__name__}`" for c in [*chain, part_of]
                            )
                            raise ConfigurationError(
                                {
                                    "element": (
                                        f"The `part_of` chain {names} loops back "
                                        "on itself; an entity chain must end at "
                                        "an aggregate"
                                    )
                                }
                            )
                        chain.append(part_of)
                        part_of = part_of.meta_.part_of

                element.cls.meta_.aggregate_cluster = part_of

    def set_aggregate_cluster_options(self) -> None:
        """Propagate aggregate-level options (like provider) to child entities."""
        registry = self._domain._domain_registry
        for element in registry._elements[DomainObjects.ENTITY.value].values():
            if not hasattr(element.cls.meta_, "provider"):
                element.cls.meta_.provider = (
                    element.cls.meta_.aggregate_cluster.meta_.provider
                )
