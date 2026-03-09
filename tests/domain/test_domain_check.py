"""Tests for Domain.check() — the structured diagnostic report method.

Domain.check() runs all init steps (via _prepare()) and all validation
checks (via validate_all()), then builds the IR for additional diagnostics.
It returns a structured dict with errors, warnings, diagnostics, and counts.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.fields import HasOne, String
from protean.utils.mixins import handle


# ─── Element definitions ────────────────────────────────────────────────


class Order(BaseAggregate):
    name: String(required=True)


class OrderPlaced(BaseEvent):
    name: String(required=True)


class PlaceOrder(BaseCommand):
    name: String(required=True)


class PlaceOrderHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def handle_place_order(self, command):
        pass


# ─── Tests ──────────────────────────────────────────────────────────────


class TestDomainCheckClean:
    """A fully wired domain returns status=pass with no issues."""

    @pytest.mark.no_test_domain
    def test_clean_domain_returns_pass(self):
        domain = Domain(name="CleanDomain", root_path=__file__)
        domain.register(Order)
        domain.register(PlaceOrder, part_of=Order)
        domain.register(PlaceOrderHandler, part_of=Order)

        result = domain.check(traverse=False)

        assert result["domain"] == "CleanDomain"
        assert result["status"] == "pass"
        assert result["errors"] == []
        assert result["warnings"] == []
        assert result["counts"]["errors"] == 0
        assert result["counts"]["warnings"] == 0

    @pytest.mark.no_test_domain
    def test_check_returns_expected_keys(self):
        domain = Domain(name="KeyCheck", root_path=__file__)
        domain.register(Order)
        result = domain.check(traverse=False)

        expected_keys = {
            "domain",
            "status",
            "errors",
            "warnings",
            "diagnostics",
            "counts",
        }
        assert set(result.keys()) == expected_keys
        assert set(result["counts"].keys()) == {"errors", "warnings", "diagnostics"}


class TestDomainCheckWarnings:
    """Domains with warnings but no errors return status=warn."""

    @pytest.mark.no_test_domain
    def test_unused_command_produces_warning(self):
        domain = Domain(name="WarnDomain", root_path=__file__)
        domain.register(Order)
        domain.register(PlaceOrder, part_of=Order)
        # No handler registered — command is unused

        result = domain.check(traverse=False)

        assert result["status"] == "warn"
        assert result["errors"] == []
        assert result["counts"]["warnings"] > 0

        codes = [w["code"] for w in result["warnings"]]
        assert "UNUSED_COMMAND" in codes

    @pytest.mark.no_test_domain
    def test_es_event_missing_apply_produces_warning(self):
        class ESAggregate(BaseAggregate):
            name: String(required=True)

        class ESEvent(BaseEvent):
            name: String(required=True)

        domain = Domain(name="ESWarnDomain", root_path=__file__)
        domain.register(ESAggregate, is_event_sourced=True)
        domain.register(ESEvent, part_of=ESAggregate)

        result = domain.check(traverse=False)

        assert result["status"] == "warn"
        codes = [w["code"] for w in result["warnings"]]
        assert "ES_EVENT_MISSING_APPLY" in codes


class TestDomainCheckErrors:
    """Domains with structural errors return status=fail."""

    @pytest.mark.no_test_domain
    def test_identity_strategy_error(self):
        domain = Domain(name="ErrDomain", root_path=__file__)
        domain.config["identity_strategy"] = "function"
        domain.register(Order)

        result = domain.check(traverse=False)

        assert result["status"] == "fail"
        assert result["counts"]["errors"] > 0
        assert any("Identity Strategy" in e["message"] for e in result["errors"])

    @pytest.mark.no_test_domain
    def test_cross_aggregate_has_one_error(self):
        class Inventory(BaseAggregate):
            name: String()

        class InventoryItem(BaseEntity):
            sku: String()

        class BadAggregate(BaseAggregate):
            name: String()
            item: HasOne("InventoryItem")

        domain = Domain(name="CrossAggDomain", root_path=__file__)
        domain.register(Inventory)
        domain.register(InventoryItem, part_of=Inventory)
        domain.register(BadAggregate)

        result = domain.check(traverse=False)

        assert result["status"] == "fail"
        assert result["counts"]["errors"] > 0

    @pytest.mark.no_test_domain
    def test_errors_and_warnings_both_collected(self):
        """When errors and warnings coexist, status is fail and both are populated."""
        domain = Domain(name="MixedDomain", root_path=__file__)
        domain.config["identity_strategy"] = "function"
        domain.register(Order)
        domain.register(PlaceOrder, part_of=Order)
        # No handler → warning; identity_strategy=function without function → error

        result = domain.check(traverse=False)

        assert result["status"] == "fail"
        assert result["counts"]["errors"] > 0
        assert result["counts"]["warnings"] > 0


class TestDomainCheckDiagnostics:
    """IR diagnostics are included when there are no fatal errors."""

    @pytest.mark.no_test_domain
    def test_diagnostics_included_when_no_errors(self):
        domain = Domain(name="DiagDomain", root_path=__file__)
        domain.register(Order)
        domain.register(PlaceOrder, part_of=Order)
        # Unused command will appear in both warnings and IR diagnostics

        result = domain.check(traverse=False)

        assert result["status"] == "warn"
        # Diagnostics should be a list (possibly empty depending on IR builder)
        assert isinstance(result["diagnostics"], list)

    @pytest.mark.no_test_domain
    def test_diagnostics_empty_when_errors_present(self):
        domain = Domain(name="ErrNoDiag", root_path=__file__)
        domain.config["identity_strategy"] = "function"
        domain.register(Order)

        result = domain.check(traverse=False)

        assert result["status"] == "fail"
        assert result["diagnostics"] == []
        assert result["counts"]["diagnostics"] == 0


class TestPrepareRefactoring:
    """Verify that init() still works correctly after the _prepare() extraction."""

    @pytest.mark.no_test_domain
    def test_init_still_works(self):
        """init() delegates to _prepare() and then initializes adapters."""
        domain = Domain(name="InitTest", root_path=__file__)
        domain.register(Order)
        domain.register(OrderPlaced, part_of=Order)
        domain.register(PlaceOrder, part_of=Order)
        domain.register(PlaceOrderHandler, part_of=Order)

        # Should not raise
        domain.init(traverse=False)

    @pytest.mark.no_test_domain
    def test_init_still_raises_on_error(self):
        """init() should still fail fast on the first validation error."""
        domain = Domain(name="InitErrTest", root_path=__file__)
        domain.config["identity_strategy"] = "function"
        domain.register(Order)

        with pytest.raises(Exception):
            domain.init(traverse=False)
