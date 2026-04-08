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
        self._warnings: list[dict[str, str]] = []
        self._errors: list[dict[str, str]] = []

    @property
    def warnings(self) -> list[dict[str, str]]:
        """Return collected warnings as structured diagnostics."""
        return list(self._warnings)

    @property
    def errors(self) -> list[dict[str, str]]:
        """Return collected errors as structured diagnostics."""
        return list(self._errors)

    def reset(self) -> None:
        """Clear all collected warnings and errors."""
        self._warnings.clear()
        self._errors.clear()

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

        Raises on the first error encountered (fail-fast behavior used
        by ``Domain.init()``).
        """
        self._validate_identity_config()
        self._validate_association_fields()
        self._validate_event_sourced_aggregates()
        self._validate_entity_providers()
        self._validate_projector_associations()
        self._validate_query_associations()
        self._validate_query_handler_associations()
        self._validate_outbox_subscription_consistency()
        self._validate_priority_lanes_config()
        self._warn_low_pool_size()
        self._warn_unhandled_commands()
        self._warn_missing_apply_handlers()
        self._warn_published_events_without_external_brokers()

    def validate_all(self) -> None:
        """Run all domain validation checks, collecting every issue.

        Unlike :meth:`validate`, this method does **not** abort on the
        first error.  Each validation is wrapped in a try/except so that
        all errors are captured in :attr:`errors`.

        Warning-level checks (unhandled commands, missing @apply handlers,
        published events without brokers) are **not** run here — they are
        handled by IR diagnostics in ``IRBuilder._collect_diagnostics()``,
        which provides a unified diagnostic model with severity levels.

        This is the entry point used by ``Domain.check()`` and the
        ``protean check`` CLI.
        """
        self.reset()

        validators = [
            self._validate_identity_config,
            self._validate_association_fields,
            self._validate_event_sourced_aggregates,
            self._validate_entity_providers,
            self._validate_projector_associations,
            self._validate_query_associations,
            self._validate_query_handler_associations,
            self._validate_outbox_subscription_consistency,
            self._validate_priority_lanes_config,
        ]

        for validator_fn in validators:
            try:
                validator_fn()
            except (ConfigurationError, IncorrectUsageError) as exc:
                raw = exc.args[0] if exc.args else str(exc)
                # Some validators pass a dict (e.g. {"element": "..."})
                message = (
                    raw.get("element", str(raw)) if isinstance(raw, dict) else str(raw)
                )
                self._errors.append(
                    {
                        "code": type(exc).__name__,
                        "element": validator_fn.__name__,
                        "level": "error",
                        "message": message,
                    }
                )

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

    def _validate_outbox_subscription_consistency(self) -> None:
        """Check that outbox and subscription type config are compatible."""
        domain = self._domain
        subscription_type = domain.config.get("server", {}).get(
            "default_subscription_type", "event_store"
        )
        if (
            domain.config.get("enable_outbox", False)
            and subscription_type == "event_store"
        ):
            raise ConfigurationError(
                "Configuration conflict: 'enable_outbox' is True but "
                "'server.default_subscription_type' is 'event_store'. "
                "When outbox is enabled, subscription type must be 'stream' "
                "so that subscriptions read from the broker where the outbox publishes. "
                "Either set server.default_subscription_type = 'stream' or remove enable_outbox."
            )

    def _validate_priority_lanes_config(self) -> None:
        """Check that priority lanes configuration values are well-typed."""
        lanes_config = self._domain.config.get("server", {}).get("priority_lanes", {})
        if not lanes_config:
            return

        enabled = lanes_config.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ConfigurationError(
                f"server.priority_lanes.enabled must be a bool, "
                f"got {type(enabled).__name__}: {enabled!r}"
            )

        threshold = lanes_config.get("threshold", 0)
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise ConfigurationError(
                f"server.priority_lanes.threshold must be an integer, "
                f"got {type(threshold).__name__}: {threshold!r}"
            )

        suffix = lanes_config.get("backfill_suffix", "backfill")
        if not isinstance(suffix, str) or not suffix.strip():
            raise ConfigurationError(
                f"server.priority_lanes.backfill_suffix must be a non-empty string, "
                f"got {type(suffix).__name__}: {suffix!r}"
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
                message = (
                    f"Command `{cmd_record.cls.__name__}` "
                    f"does not have a registered handler"
                )
                self._warnings.append(
                    {
                        "code": "UNUSED_COMMAND",
                        "element": fqn(cmd_record.cls),
                        "level": "warning",
                        "message": message,
                    }
                )
                logger.warning(message)

    def _warn_missing_apply_handlers(self) -> None:
        """Warn about events on event-sourced aggregates missing @apply handlers."""
        registry = self._domain.registry
        for _, agg_record in registry._elements[DomainObjects.AGGREGATE.value].items():
            if not agg_record.cls.meta_.is_event_sourced:
                continue

            for _, evt_record in registry._elements[DomainObjects.EVENT.value].items():
                # Skip fact events — they are auto-generated and not
                # expected to have @apply handlers.
                if evt_record.cls.meta_.is_fact_event:
                    continue

                if (
                    evt_record.cls.meta_.part_of == agg_record.cls
                    and not evt_record.cls.meta_.abstract
                    and fqn(evt_record.cls) not in agg_record.cls._projections
                ):
                    message = (
                        f"Event `{evt_record.cls.__name__}` on event-sourced "
                        f"aggregate `{agg_record.cls.__name__}` "
                        f"does not have an @apply handler"
                    )
                    self._warnings.append(
                        {
                            "code": "ES_EVENT_MISSING_APPLY",
                            "element": fqn(evt_record.cls),
                            "level": "warning",
                            "message": message,
                        }
                    )
                    logger.warning(message)

    # Minimum pool_size before a warning is emitted.  Kept in sync with
    # the defaults in PostgresqlProvider / MssqlProvider.
    _MIN_PRODUCTION_POOL_SIZE = 5

    def _warn_low_pool_size(self) -> None:
        """Warn when a database provider has pool_size below the production default."""
        databases = self._domain.config.get("databases", {})
        for db_name, db_config in databases.items():
            if not isinstance(db_config, dict):
                continue
            pool_size = db_config.get("pool_size")
            if pool_size is not None and pool_size < self._MIN_PRODUCTION_POOL_SIZE:
                provider = db_config.get("provider", "unknown")
                # Skip memory provider — it doesn't use connection pools
                if provider == "memory":
                    continue
                message = (
                    f"Database '{db_name}' has pool_size={pool_size} "
                    f"(production default is {self._MIN_PRODUCTION_POOL_SIZE}). "
                    f"Consider raising it for production workloads."
                )
                self._warnings.append(
                    {
                        "code": "LOW_POOL_SIZE",
                        "element": f"databases.{db_name}",
                        "level": "warning",
                        "message": message,
                    }
                )
                logger.warning(message)

    def _warn_published_events_without_external_brokers(self) -> None:
        """Warn when published events exist but no external brokers are configured."""
        external_brokers = self._domain.config.get("outbox", {}).get(
            "external_brokers", []
        )
        if external_brokers:
            return

        registry = self._domain.registry
        has_published = any(
            getattr(record.cls.meta_, "published", False)
            for record in registry._elements.get(DomainObjects.EVENT.value, {}).values()
        )
        if has_published:
            message = (
                "Domain has published events but no external_brokers "
                "configured in outbox settings. Published events will "
                "only be dispatched internally."
            )
            self._warnings.append(
                {
                    "code": "PUBLISHED_NO_EXTERNAL_BROKER",
                    "element": self._domain.name,
                    "level": "warning",
                    "message": message,
                }
            )
            logger.warning(message)
