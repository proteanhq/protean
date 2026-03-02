"""Element resolution logic extracted from the Domain class.

The ``ElementResolver`` resolves string-based references between domain
elements (e.g. ``HasMany("Comment")`` → actual ``Comment`` class) and
assigns aggregate clusters so that entities, events, and commands know
which aggregate root they belong to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from protean.exceptions import ConfigurationError, NotSupportedError
from protean.utils import DomainObjects

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
        report them with contextual error messages.
        """
        pending = self._domain._pending_class_resolutions
        for name in list(pending.keys()):
            resolved = True
            for resolution_type, params in pending[name]:
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
                            to_cls = self._domain.fetch_element_cls_from_registry(
                                cls.meta_.part_of,
                                (DomainObjects.AGGREGATE,),
                            )
                            cls.meta_.part_of = to_cls
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
                    resolved = False

            if resolved:
                del pending[name]

    def assign_aggregate_clusters(self) -> None:
        """Assign aggregate clusters to all relevant elements."""
        from protean.core.aggregate import BaseAggregate
        from protean.core.process_manager import BaseProcessManager

        registry = self._domain._domain_registry

        # Assign Aggregates and Process Managers to their own cluster
        for element_type in [DomainObjects.AGGREGATE, DomainObjects.PROCESS_MANAGER]:
            for _, element in registry._elements[element_type.value].items():
                element.cls.meta_.aggregate_cluster = element.cls

        # Derive root aggregate for other elements
        for element_type in [
            DomainObjects.ENTITY,
            DomainObjects.EVENT,
            DomainObjects.COMMAND,
        ]:
            for _, element in registry._elements[element_type.value].items():
                part_of = element.cls.meta_.part_of
                if part_of:
                    # Traverse up the graph tree to find the root aggregate
                    while not issubclass(part_of, BaseAggregate) and not issubclass(
                        part_of, BaseProcessManager
                    ):
                        part_of = part_of.meta_.part_of

                element.cls.meta_.aggregate_cluster = part_of

    def set_aggregate_cluster_options(self) -> None:
        """Propagate aggregate-level options (like provider) to child entities."""
        registry = self._domain._domain_registry
        for _, element in registry._elements[DomainObjects.ENTITY.value].items():
            if not hasattr(element.cls.meta_, "provider"):
                setattr(
                    element.cls.meta_,
                    "provider",
                    element.cls.meta_.aggregate_cluster.meta_.provider,
                )
