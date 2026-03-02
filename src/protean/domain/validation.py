"""Domain validation logic extracted from the Domain class.

The ``DomainValidator`` runs post-registration checks on the entire domain
graph to catch configuration errors, invalid associations, and missing
handlers before the domain is activated.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.fields import HasMany, HasOne
from protean.utils import DomainObjects, fqn
from protean.utils.reflection import declared_fields

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class DomainValidator:
    """Validates the domain configuration for correctness.

    Instantiated once by ``Domain.__init__()`` and called during
    ``Domain.init()`` after reference resolution and handler setup.

    The monolithic ``_validate_domain()`` is decomposed into focused
    private methods, each responsible for one category of validation.
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_unresolved_references(self) -> None:
        """Raise a ``ConfigurationError`` if any string references remain unresolved.

        Called right after ``_resolve_references()`` to fail fast with
        contextual error messages before later init steps (like
        ``_assign_aggregate_clusters``) assume all references are resolved.
        """
        pending = self._domain._pending_class_resolutions
        if not pending:
            return

        details: list[str] = []
        for target_name, pending_list in pending.items():
            for resolution_type, params in pending_list:
                match resolution_type:
                    case "Association":
                        field_obj, owner_cls = params
                        details.append(
                            f"`{owner_cls.__name__}.{field_obj.field_name}` "
                            f"references `{target_name}` via "
                            f"{type(field_obj).__name__}"
                        )
                    case "ValueObject":
                        field_obj, owner_cls = params
                        details.append(
                            f"`{owner_cls.__name__}.{field_obj.field_name}` "
                            f"references `{target_name}` via ValueObject"
                        )
                    case "AggregateCls":
                        cls = params
                        details.append(
                            f"`{cls.__name__}` references `{target_name}` via part_of"
                        )
                    case "ProjectionCls":
                        cls = params
                        details.append(
                            f"`{cls.__name__}` references `{target_name}` "
                            f"via projector_for"
                        )
                    case "QueryProjectionCls" | "QueryHandlerProjectionCls":
                        cls = params
                        details.append(
                            f"`{cls.__name__}` references `{target_name}` via part_of"
                        )
        raise ConfigurationError(
            {
                "element": (
                    f"Unresolved references in domain `{self._domain.name}`: "
                    + "; ".join(details)
                ),
            }
        )

    def validate(self) -> None:
        """Run all domain validation checks.

        Called just before the domain is activated.  Each private method
        is responsible for one category of validation, making it easier
        to test and extend.
        """
        self._validate_identity_config()
        self._validate_association_fields()
        self._validate_event_sourced_aggregates()
        self._validate_entity_providers()
        self._validate_projector_associations()
        self._validate_query_associations()
        self._validate_query_handler_associations()
        self._warn_unhandled_commands()
        self._warn_missing_apply_handlers()

    # ------------------------------------------------------------------
    # Private validation methods
    # ------------------------------------------------------------------

    def _validate_identity_config(self) -> None:
        """Check ``identity_function`` is provided when ``identity_strategy`` is ``function``."""
        domain = self._domain
        if domain.config["identity_strategy"] == domain.IdentityStrategy.FUNCTION.value:
            if not domain._identity_function:
                raise ConfigurationError(
                    {
                        "element": "Identity Strategy is set to `function`, but no Identity Function is provided"
                    }
                )

    def _validate_association_fields(self) -> None:
        """Validate ``HasOne`` and ``HasMany`` fields on aggregates and entities.

        Checks:
        1. Target must be resolved (not a dangling string reference)
        2. Target must be an Entity (not an Aggregate)
        3. Target must belong to the same aggregate cluster as the owner
        """
        registry = self._domain.registry
        owner_elements = list(registry.aggregates.items()) + list(
            registry._elements[DomainObjects.ENTITY.value].items()
        )
        for _, element in owner_elements:
            owner_cls = element.cls
            for _, field_obj in declared_fields(owner_cls).items():
                if isinstance(field_obj, (HasOne, HasMany)):
                    if isinstance(field_obj.to_cls, str):
                        raise IncorrectUsageError(
                            f"Unresolved target `{field_obj.to_cls}` for field "
                            f"`{owner_cls.__name__}:{field_obj.name}`"
                        )
                    if field_obj.to_cls.element_type != DomainObjects.ENTITY:
                        raise IncorrectUsageError(
                            f"Field `{field_obj.field_name}` in `{owner_cls.__name__}` "
                            "is not linked to an Entity class"
                        )
                    if (
                        field_obj.to_cls.meta_.aggregate_cluster
                        != owner_cls.meta_.aggregate_cluster
                    ):
                        raise IncorrectUsageError(
                            f"Field `{field_obj.field_name}` in `{owner_cls.__name__}` "
                            f"points to `{field_obj.to_cls.__name__}` which belongs to "
                            f"a different aggregate "
                            f"`{field_obj.to_cls.meta_.aggregate_cluster.__name__}`. "
                            f"HasOne/HasMany associations must target entities within "
                            f"the same aggregate cluster."
                        )

    def _validate_event_sourced_aggregates(self) -> None:
        """Check that no two event sourced aggregates share the same event class."""
        registry = self._domain.registry
        event_sourced_aggregates = {
            name: record
            for (name, record) in registry._elements[
                DomainObjects.AGGREGATE.value
            ].items()
            if record.cls.meta_.is_event_sourced is True
        }

        event_class_names: list[str] = []
        for es_agg in event_sourced_aggregates.values():
            event_class_names.extend(es_agg.cls._events_cls_map.keys())

        duplicate_event_class_names = {
            name for name in event_class_names if event_class_names.count(name) > 1
        }
        if duplicate_event_class_names:
            raise IncorrectUsageError(
                f"Events are associated with multiple event sourced aggregates: "
                f"{', '.join(duplicate_event_class_names)}"
            )

    def _validate_entity_providers(self) -> None:
        """Check that entities have the same provider as their aggregate."""
        registry = self._domain.registry
        for _, entity in registry._elements[DomainObjects.ENTITY.value].items():
            if (
                entity.cls.meta_.aggregate_cluster.meta_.provider
                != entity.cls.meta_.provider
            ):
                raise IncorrectUsageError(
                    f"Entity `{entity.cls.__name__}` has a different provider "
                    f"than its aggregate `{entity.cls.meta_.aggregate_cluster.__name__}`"
                )

    def _validate_projector_associations(self) -> None:
        """Check that projections associated with projectors are registered."""
        registry = self._domain.registry
        for _, projector in registry._elements[DomainObjects.PROJECTOR.value].items():
            if projector.cls.meta_.projector_for:
                if (
                    fqn(projector.cls.meta_.projector_for)
                    not in registry._elements[DomainObjects.PROJECTION.value]
                ):
                    raise IncorrectUsageError(
                        f"`{projector.cls.meta_.projector_for.__name__}` is not a Projection, "
                        f"or is not registered in domain {self._domain.name}"
                    )

    def _validate_query_associations(self) -> None:
        """Check that queries are associated with registered projections."""
        registry = self._domain.registry
        for _, query_record in registry._elements[DomainObjects.QUERY.value].items():
            if query_record.cls.meta_.part_of:
                if (
                    fqn(query_record.cls.meta_.part_of)
                    not in registry._elements[DomainObjects.PROJECTION.value]
                ):
                    raise IncorrectUsageError(
                        f"`{query_record.cls.meta_.part_of.__name__}` is not a Projection, "
                        f"or is not registered in domain {self._domain.name}"
                    )

    def _validate_query_handler_associations(self) -> None:
        """Check that query handlers are associated with registered projections."""
        registry = self._domain.registry
        for _, qh_record in registry._elements[
            DomainObjects.QUERY_HANDLER.value
        ].items():
            if qh_record.cls.meta_.part_of:
                if (
                    fqn(qh_record.cls.meta_.part_of)
                    not in registry._elements[DomainObjects.PROJECTION.value]
                ):
                    raise IncorrectUsageError(
                        f"`{qh_record.cls.meta_.part_of.__name__}` is not a Projection, "
                        f"or is not registered in domain {self._domain.name}"
                    )

    def _warn_unhandled_commands(self) -> None:
        """Warn about registered Commands that have no handler."""
        registry = self._domain.registry
        all_handled_command_types: set[str] = set()
        for _, ch_record in registry._elements[
            DomainObjects.COMMAND_HANDLER.value
        ].items():
            all_handled_command_types.update(ch_record.cls._handlers.keys())

        for _, cmd_record in registry._elements[DomainObjects.COMMAND.value].items():
            if (
                not cmd_record.cls.meta_.abstract
                and cmd_record.cls.__type__ not in all_handled_command_types
            ):
                logger.warning(
                    "Command `%s` does not have a registered handler",
                    cmd_record.cls.__name__,
                )

    def _warn_missing_apply_handlers(self) -> None:
        """Warn about events on event-sourced aggregates missing @apply handlers."""
        registry = self._domain.registry
        for _, agg_record in registry._elements[DomainObjects.AGGREGATE.value].items():
            if not agg_record.cls.meta_.is_event_sourced:
                continue

            for _, evt_record in registry._elements[DomainObjects.EVENT.value].items():
                # Skip fact events — they are auto-generated and not
                # expected to have @apply handlers.
                if evt_record.cls.__name__.endswith("FactEvent"):
                    continue

                if (
                    evt_record.cls.meta_.part_of == agg_record.cls
                    and not evt_record.cls.meta_.abstract
                    and fqn(evt_record.cls) not in agg_record.cls._projections
                ):
                    logger.warning(
                        "Event `%s` on event-sourced aggregate `%s` "
                        "does not have an @apply handler",
                        evt_record.cls.__name__,
                        agg_record.cls.__name__,
                    )
