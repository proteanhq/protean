"""Tests for DomainValidator — the extracted domain validation logic.

These tests exercise the validator methods through ``Domain.init()``
(the same way they run in production) to verify that the extracted
``DomainValidator`` class catches configuration errors and emits
appropriate warnings.
"""

import logging

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.domain import Domain
from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.fields import HasMany, HasOne, Identifier, String
from protean.utils.mixins import handle, read


# ─── Shared element definitions ─────────────────────────────────────────


class Account(BaseAggregate):
    name: String(required=True)


class AccountEntity(BaseEntity):
    label: String()


class AccountCreated(BaseEvent):
    name: String(required=True)


class CreateAccount(BaseCommand):
    name: String(required=True)


# ─── check_unresolved_references (brief, detailed coverage elsewhere) ───


class TestCheckUnresolvedReferences:
    """Brief test that check_unresolved_references raises ConfigurationError.

    Full coverage lives in ``test_unresolved_reference_errors.py``.
    """

    @pytest.mark.no_test_domain
    def test_unresolved_has_many_raises_configuration_error(self):
        domain = Domain(__name__, "Tests")

        class Parent(BaseAggregate):
            name: String()
            children = HasMany("NonExistentChild")

        domain.register(Parent)

        with pytest.raises(ConfigurationError, match="Unresolved references"):
            domain.init(traverse=False)


# ─── _validate_identity_config ──────────────────────────────────────────


class TestValidateIdentityConfig:
    """Validates identity_strategy=function requires an identity_function."""

    @pytest.mark.no_test_domain
    def test_function_strategy_without_identity_function_raises_error(self):
        domain = Domain()
        domain.config["identity_strategy"] = "function"

        class Dummy(BaseAggregate):
            pass

        domain.register(Dummy)

        with pytest.raises(ConfigurationError, match="no Identity Function"):
            domain.init(traverse=False)

    @pytest.mark.no_test_domain
    def test_function_strategy_with_identity_function_passes(self):
        domain = Domain(identity_function=lambda: "test-id")
        domain.config["identity_strategy"] = "function"

        class Dummy(BaseAggregate):
            pass

        domain.register(Dummy)
        domain.init(traverse=False)  # Should not raise

    def test_uuid_strategy_passes_without_identity_function(self, test_domain):
        """Default uuid strategy should not require an identity function."""
        test_domain.register(Account)
        test_domain.init(traverse=False)  # Should not raise


# ─── _validate_association_fields ───────────────────────────────────────


class TestValidateAssociationFields:
    """Validates HasOne/HasMany field targets and cluster membership."""

    def test_valid_has_one_within_same_cluster_passes(self, test_domain):
        class Order(BaseAggregate):
            name: String()
            detail = HasOne("OrderDetail")

        class OrderDetail(BaseEntity):
            info: String()

        test_domain.register(Order)
        test_domain.register(OrderDetail, part_of=Order)
        test_domain.init(traverse=False)  # Should not raise

    def test_valid_has_many_within_same_cluster_passes(self, test_domain):
        class Catalog(BaseAggregate):
            name: String()
            items = HasMany("CatalogItem")

        class CatalogItem(BaseEntity):
            sku: String()

        test_domain.register(Catalog)
        test_domain.register(CatalogItem, part_of=Catalog)
        test_domain.init(traverse=False)  # Should not raise

    def test_has_one_targeting_cross_cluster_entity_raises_error(self, test_domain):
        class Warehouse(BaseAggregate):
            name: String()

        class Shelf(BaseEntity):
            label: String()

        class Store(BaseAggregate):
            name: String()
            shelf = HasOne("Shelf")

        test_domain.register(Warehouse)
        test_domain.register(Shelf, part_of=Warehouse)
        test_domain.register(Store)

        with pytest.raises(IncorrectUsageError, match="different aggregate"):
            test_domain.init(traverse=False)

    def test_has_many_targeting_cross_cluster_entity_raises_error(self, test_domain):
        class Dept(BaseAggregate):
            name: String()

        class Worker(BaseEntity):
            name: String()

        class Project(BaseAggregate):
            name: String()
            workers = HasMany("Worker")

        test_domain.register(Dept)
        test_domain.register(Worker, part_of=Dept)
        test_domain.register(Project)

        with pytest.raises(IncorrectUsageError, match="different aggregate"):
            test_domain.init(traverse=False)


# ─── _validate_event_sourced_aggregates ─────────────────────────────────


class TestValidateEventSourcedAggregates:
    """Validates that event classes are not shared across event-sourced aggregates."""

    def test_single_event_sourced_aggregate_passes(self, test_domain):
        class Ledger(BaseAggregate):
            name: String()

            @apply
            def on_created(self, event: AccountCreated) -> None:
                pass

        test_domain.register(Ledger, is_event_sourced=True)
        test_domain.register(AccountCreated, part_of=Ledger)
        test_domain.init(traverse=False)  # Should not raise

    def test_duplicate_event_across_es_aggregates_raises_error(self, test_domain):
        class SharedEvent(BaseEvent):
            data: String()

        class AggA(BaseAggregate):
            name: String()

            @apply
            def on_shared(self, event: SharedEvent) -> None:
                pass

        class AggB(BaseAggregate):
            name: String()

            @apply
            def on_shared(self, event: SharedEvent) -> None:
                pass

        test_domain.register(AggA, is_event_sourced=True)
        test_domain.register(AggB, is_event_sourced=True)
        test_domain.register(SharedEvent, part_of=AggA)

        # Manually wire the event into both aggregates' _events_cls_map
        # to simulate the duplicate condition
        from protean.utils import fqn

        AggB._events_cls_map[fqn(SharedEvent)] = SharedEvent

        with pytest.raises(
            IncorrectUsageError, match="associated with multiple event sourced"
        ):
            test_domain.init(traverse=False)


# ─── _validate_entity_providers ─────────────────────────────────────────


class TestValidateEntityProviders:
    """Validates that entities inherit the same provider as their aggregate."""

    def test_matching_providers_passes(self, test_domain):
        class Dept(BaseAggregate):
            name: String()
            dean = HasOne("Dean")

        class Dean(BaseEntity):
            name: String()

        test_domain.register(Dept, provider="primary")
        test_domain.register(Dean, part_of=Dept, provider="primary")
        test_domain.init(traverse=False)  # Should not raise

    def test_mismatched_providers_raises_error(self, test_domain):
        class Dept(BaseAggregate):
            name: String()
            dean = HasOne("Dean")

        class Dean(BaseEntity):
            name: String()

        test_domain.register(Dept, provider="primary")
        test_domain.register(Dean, part_of=Dept, provider="secondary")

        with pytest.raises(IncorrectUsageError, match="different provider"):
            test_domain.init(traverse=False)

    def test_default_providers_pass(self, test_domain):
        class Company(BaseAggregate):
            name: String()
            office = HasOne("Office")

        class Office(BaseEntity):
            location: String()

        test_domain.register(Company)
        test_domain.register(Office, part_of=Company)
        test_domain.init(traverse=False)  # Should not raise


# ─── _validate_projector_associations ───────────────────────────────────


class TestValidateProjectorAssociations:
    """Validates that projectors reference registered projections."""

    def test_projector_for_registered_projection_passes(self, test_domain):
        class UserProjection(BaseProjection):
            user_id: Identifier(identifier=True)
            name: String()

        class UserProjector(BaseProjector):
            @handle(AccountCreated)
            def on_created(self, event: AccountCreated) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(UserProjection)
        test_domain.register(
            UserProjector, projector_for=UserProjection, aggregates=[Account]
        )
        test_domain.init(traverse=False)  # Should not raise

    def test_projector_for_unregistered_projection_raises_error(self, test_domain):
        class GhostProjection(BaseProjection):
            ghost_id: Identifier(identifier=True)
            name: String()

        class BadProjector(BaseProjector):
            pass

        test_domain.register(Account)
        # Register projector but NOT the projection
        test_domain.register(
            BadProjector, projector_for=GhostProjection, aggregates=[Account]
        )

        with pytest.raises(IncorrectUsageError, match="is not a Projection"):
            test_domain.init(traverse=False)


# ─── _validate_query_associations ───────────────────────────────────────


class TestValidateQueryAssociations:
    """Validates that queries reference registered projections."""

    def test_query_for_registered_projection_passes(self, test_domain):
        class ItemProjection(BaseProjection):
            item_id: Identifier(identifier=True)
            name: String()

        class FindItems(BaseQuery):
            keyword: String()

        test_domain.register(ItemProjection)
        test_domain.register(FindItems, part_of=ItemProjection)
        test_domain.init(traverse=False)  # Should not raise

    def test_query_for_unregistered_projection_raises_error(self, test_domain):
        class MissingProjection(BaseProjection):
            proj_id: Identifier(identifier=True)
            name: String()

        class SearchItems(BaseQuery):
            keyword: String()

        # Register query with part_of pointing to unregistered projection
        test_domain.register(SearchItems, part_of=MissingProjection)

        with pytest.raises(IncorrectUsageError, match="is not a Projection"):
            test_domain.init(traverse=False)


# ─── _validate_query_handler_associations ───────────────────────────────


class TestValidateQueryHandlerAssociations:
    """Validates that query handlers reference registered projections."""

    def test_query_handler_for_registered_projection_passes(self, test_domain):
        class ReportProjection(BaseProjection):
            report_id: Identifier(identifier=True)
            title: String()

        class GetReport(BaseQuery):
            report_id: Identifier()

        class ReportQueryHandler(BaseQueryHandler):
            @read(GetReport)
            def get(self, query: GetReport):
                pass

        test_domain.register(ReportProjection)
        test_domain.register(GetReport, part_of=ReportProjection)
        test_domain.register(ReportQueryHandler, part_of=ReportProjection)
        test_domain.init(traverse=False)  # Should not raise

    def test_query_handler_for_unregistered_projection_raises_error(self, test_domain):
        class AbsentProjection(BaseProjection):
            absent_id: Identifier(identifier=True)
            name: String()

        class FetchData(BaseQuery):
            data_id: Identifier()

        class DataQueryHandler(BaseQueryHandler):
            @read(FetchData)
            def fetch(self, query: FetchData):
                pass

        # Register query and handler with part_of pointing to unregistered projection
        test_domain.register(FetchData, part_of=AbsentProjection)
        test_domain.register(DataQueryHandler, part_of=AbsentProjection)

        with pytest.raises(IncorrectUsageError, match="is not a Projection"):
            test_domain.init(traverse=False)


# ─── _warn_unhandled_commands ───────────────────────────────────────────


class TestWarnUnhandledCommands:
    """Validates that commands without handlers produce warnings."""

    def test_unhandled_command_logs_warning(self, test_domain, caplog):
        test_domain.register(Account)
        test_domain.register(CreateAccount, part_of=Account)

        with caplog.at_level(logging.WARNING, logger="protean.domain.validation"):
            test_domain.init(traverse=False)

        assert any(
            "CreateAccount" in r.message and "handler" in r.message
            for r in caplog.records
        )

    def test_handled_command_no_warning(self, test_domain, caplog):
        class Handler(BaseCommandHandler):
            @handle(CreateAccount)
            def create(self, command: CreateAccount) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(Handler, part_of=Account)

        with caplog.at_level(logging.WARNING, logger="protean.domain.validation"):
            test_domain.init(traverse=False)

        assert not any(
            "CreateAccount" in r.message and "handler" in r.message
            for r in caplog.records
        )


# ─── _warn_missing_apply_handlers ──────────────────────────────────────


class TestWarnMissingApplyHandlers:
    """Validates that events on ES aggregates without @apply produce warnings."""

    def test_event_without_apply_handler_logs_warning(self, test_domain, caplog):
        class ESAggregate(BaseAggregate):
            name: String()
            # No @apply handler for AccountCreated

        test_domain.register(ESAggregate, is_event_sourced=True)
        test_domain.register(AccountCreated, part_of=ESAggregate)

        with caplog.at_level(logging.WARNING, logger="protean.domain.validation"):
            test_domain.init(traverse=False)

        assert any(
            "AccountCreated" in r.message and "@apply" in r.message
            for r in caplog.records
        )

    def test_event_with_apply_handler_no_warning(self, test_domain, caplog):
        class ESAggregate(BaseAggregate):
            name: String()

            @apply
            def on_created(self, event: AccountCreated) -> None:
                pass

        test_domain.register(ESAggregate, is_event_sourced=True)
        test_domain.register(AccountCreated, part_of=ESAggregate)

        with caplog.at_level(logging.WARNING, logger="protean.domain.validation"):
            test_domain.init(traverse=False)

        assert not any(
            "AccountCreated" in r.message and "@apply" in r.message
            for r in caplog.records
        )

    def test_non_es_aggregate_events_not_warned(self, test_domain, caplog):
        """Non-event-sourced aggregates should not trigger @apply warnings."""
        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)

        with caplog.at_level(logging.WARNING, logger="protean.domain.validation"):
            test_domain.init(traverse=False)

        assert not any("@apply" in r.message for r in caplog.records)


# ─── validate() orchestration ──────────────────────────────────────────


class TestValidateOrchestration:
    """Verify that validate() runs all sub-validators."""

    def test_valid_domain_passes_all_checks(self, test_domain):
        """A well-formed domain passes validate() without errors."""

        class Handler(BaseCommandHandler):
            @handle(CreateAccount)
            def create(self, command: CreateAccount) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(AccountEntity, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(Handler, part_of=Account)
        test_domain.init(traverse=False)  # Should not raise


# ─── Structured warnings collection ──────────────────────────────────


class TestStructuredWarnings:
    """Verify that _warn_* methods populate the warnings property with
    structured dicts matching the IR diagnostic format."""

    def test_unhandled_command_collected_as_structured_warning(self, test_domain):
        test_domain.register(Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.init(traverse=False)

        warnings = test_domain._validator.warnings
        assert len(warnings) == 1
        w = warnings[0]
        assert w["code"] == "UNUSED_COMMAND"
        assert "CreateAccount" in w["element"]
        assert w["level"] == "warning"
        assert "handler" in w["message"]

    def test_missing_apply_handler_collected_as_structured_warning(self, test_domain):
        class ESAggregate(BaseAggregate):
            name: String()

        test_domain.register(ESAggregate, is_event_sourced=True)
        test_domain.register(AccountCreated, part_of=ESAggregate)
        test_domain.init(traverse=False)

        warnings = test_domain._validator.warnings
        es_warnings = [w for w in warnings if w["code"] == "ES_EVENT_MISSING_APPLY"]
        assert len(es_warnings) == 1
        assert "AccountCreated" in es_warnings[0]["element"]
        assert "@apply" in es_warnings[0]["message"]

    @pytest.mark.no_test_domain
    def test_published_event_no_broker_collected_as_structured_warning(self):
        domain = Domain(__name__, "TestPublished")

        class Order(BaseAggregate):
            name: String()

        class OrderShipped(BaseEvent):
            order_id: String()

        domain.register(Order)
        domain.register(OrderShipped, part_of=Order, published=True)
        domain.init(traverse=False)

        warnings = domain._validator.warnings
        broker_warnings = [
            w for w in warnings if w["code"] == "PUBLISHED_NO_EXTERNAL_BROKER"
        ]
        assert len(broker_warnings) == 1
        assert "published events" in broker_warnings[0]["message"]

    def test_no_warnings_when_domain_is_well_formed(self, test_domain):
        class Handler(BaseCommandHandler):
            @handle(CreateAccount)
            def create(self, command: CreateAccount) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(Handler, part_of=Account)
        test_domain.init(traverse=False)

        assert test_domain._validator.warnings == []

    def test_warnings_property_returns_copy(self, test_domain):
        """Mutating the returned list should not affect internal state."""
        test_domain.register(Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.init(traverse=False)

        warnings = test_domain._validator.warnings
        warnings.clear()
        assert len(test_domain._validator.warnings) == 1

    def test_multiple_warnings_collected(self, test_domain):
        """Multiple warning conditions produce multiple structured entries."""

        class ESAggregate(BaseAggregate):
            name: String()

        class SomeEvent(BaseEvent):
            data: String()

        test_domain.register(ESAggregate, is_event_sourced=True)
        test_domain.register(SomeEvent, part_of=ESAggregate)
        test_domain.register(CreateAccount, part_of=ESAggregate)
        test_domain.init(traverse=False)

        warnings = test_domain._validator.warnings
        codes = {w["code"] for w in warnings}
        assert "UNUSED_COMMAND" in codes
        assert "ES_EVENT_MISSING_APPLY" in codes
