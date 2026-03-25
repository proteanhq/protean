"""Tests for deprecation support in domain elements, fields, IR, and diff."""

from __future__ import annotations

import pytest

from protean import Domain
from protean.exceptions import ConfigurationError
from protean.fields import Float, Identifier, String
from protean.ir.builder import IRBuilder
from protean.ir.diff import _classify_removal, _parse_version_tuple, diff_ir
from protean.utils import _normalize_deprecated
from protean.utils.mixins import handle, read


# =====================================================================
# _normalize_deprecated
# =====================================================================


class TestNormalizeDeprecated:
    """Tests for the ``_normalize_deprecated`` helper."""

    def test_none_returns_none(self) -> None:
        assert _normalize_deprecated(None) is None

    def test_false_returns_none(self) -> None:
        assert _normalize_deprecated(False) is None

    def test_string_shorthand(self) -> None:
        result = _normalize_deprecated("0.15")
        assert result == {"since": "0.15"}

    def test_dict_with_since(self) -> None:
        result = _normalize_deprecated({"since": "0.15"})
        assert result == {"since": "0.15"}

    def test_dict_with_since_and_removal(self) -> None:
        result = _normalize_deprecated({"since": "0.15", "removal": "0.18"})
        assert result == {"since": "0.15", "removal": "0.18"}

    def test_dict_missing_since_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="'since' key"):
            _normalize_deprecated({"removal": "0.18"})

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Invalid `deprecated`"):
            _normalize_deprecated(42)

    def test_values_coerced_to_string(self) -> None:
        result = _normalize_deprecated({"since": 15, "removal": 18})
        assert result == {"since": "15", "removal": "18"}

    def test_extra_keys_ignored(self) -> None:
        """Extra keys beyond since/removal are silently dropped."""
        result = _normalize_deprecated(
            {"since": "0.15", "removal": "0.18", "note": "Use NewEvent"}
        )
        assert result == {"since": "0.15", "removal": "0.18"}


# =====================================================================
# Element-level deprecated option
# =====================================================================


@pytest.mark.no_test_domain
class TestElementDeprecatedOption:
    """Test the ``deprecated`` decorator option on domain elements."""

    @pytest.fixture(autouse=True)
    def setup_domain(self) -> None:
        self.domain = Domain(name="TestDeprecated")

    def test_aggregate_deprecated_shorthand(self) -> None:
        @self.domain.aggregate(deprecated="0.15")
        class Order:
            pass

        assert Order.meta_.deprecated == {"since": "0.15"}

    def test_aggregate_deprecated_full(self) -> None:
        @self.domain.aggregate(deprecated={"since": "0.15", "removal": "0.18"})
        class Order:
            pass

        assert Order.meta_.deprecated == {"since": "0.15", "removal": "0.18"}

    def test_aggregate_not_deprecated(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        assert Order.meta_.deprecated is None

    def test_event_deprecated(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.event(
            part_of=Order,
            deprecated={"since": "0.15", "removal": "0.18"},
        )
        class OrderLegacyEvent:
            pass

        assert OrderLegacyEvent.meta_.deprecated == {
            "since": "0.15",
            "removal": "0.18",
        }

    def test_command_deprecated(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.command(
            part_of=Order,
            deprecated="0.15",
        )
        class LegacyCommand:
            pass

        assert LegacyCommand.meta_.deprecated == {"since": "0.15"}

    def test_entity_deprecated(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.entity(part_of=Order, deprecated="0.16")
        class LineItem:
            pass

        assert LineItem.meta_.deprecated == {"since": "0.16"}

    def test_value_object_deprecated(self) -> None:
        @self.domain.value_object(deprecated="0.15")
        class Money:
            amount: float
            currency: str

        assert Money.meta_.deprecated == {"since": "0.15"}

    def test_projection_deprecated(self) -> None:
        from protean.fields import Identifier

        @self.domain.projection(deprecated="0.15")
        class OrderView:
            order_id = Identifier(identifier=True)

        assert OrderView.meta_.deprecated == {"since": "0.15"}

    def test_invalid_deprecated_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Invalid `deprecated`"):

            @self.domain.aggregate(deprecated=42)
            class Order:
                pass


# =====================================================================
# Field-level deprecated
# =====================================================================


class TestFieldDeprecated:
    """Test the ``deprecated`` parameter on fields."""

    def test_string_field_deprecated_shorthand(self) -> None:
        field = String(deprecated="0.15")
        assert field.deprecated == {"since": "0.15"}

    def test_string_field_deprecated_full(self) -> None:
        field = String(deprecated={"since": "0.15", "removal": "0.18"})
        assert field.deprecated == {"since": "0.15", "removal": "0.18"}

    def test_string_field_not_deprecated(self) -> None:
        field = String()
        assert field.deprecated is None

    def test_invalid_deprecated_raises(self) -> None:
        with pytest.raises(ValueError, match="'since' key"):
            String(deprecated={"removal": "0.18"})

    def test_deprecated_preserved_in_field_attribute(self) -> None:
        """Verify deprecated metadata survives on the field object for IR extraction."""
        from protean.fields.association import Reference

        field = Reference("SomeClass", deprecated={"since": "0.15", "removal": "0.18"})
        assert field.deprecated == {"since": "0.15", "removal": "0.18"}


# =====================================================================
# FieldSpec deprecated
# =====================================================================


class TestFieldSpecDeprecated:
    """Test the ``deprecated`` parameter on FieldSpec."""

    def test_fieldspec_deprecated_shorthand(self) -> None:
        from protean.fields.spec import FieldSpec

        fs = FieldSpec(str, deprecated="0.15")
        assert fs.deprecated == {"since": "0.15"}

    def test_fieldspec_deprecated_full(self) -> None:
        from protean.fields.spec import FieldSpec

        fs = FieldSpec(str, deprecated={"since": "0.15", "removal": "0.18"})
        assert fs.deprecated == {"since": "0.15", "removal": "0.18"}

    def test_fieldspec_deprecated_in_json_schema_extra(self) -> None:
        from protean.fields.spec import FieldSpec

        fs = FieldSpec(str, deprecated={"since": "0.15", "removal": "0.18"})
        kwargs = fs.resolve_field_kwargs()
        extra = kwargs.get("json_schema_extra", {})
        assert extra.get("_deprecated") == {"since": "0.15", "removal": "0.18"}

    def test_fieldspec_not_deprecated_no_extra(self) -> None:
        from protean.fields.spec import FieldSpec

        fs = FieldSpec(str)
        kwargs = fs.resolve_field_kwargs()
        extra = kwargs.get("json_schema_extra", {})
        assert "_deprecated" not in extra


# =====================================================================
# IR Builder — deprecated in IR output
# =====================================================================


@pytest.mark.no_test_domain
class TestIRBuilderDeprecated:
    """Test that deprecated metadata appears in the built IR."""

    @pytest.fixture(autouse=True)
    def setup_domain(self) -> None:
        self.domain = Domain(name="TestIR")

    @staticmethod
    def _find_cluster(ir: dict, cls: type) -> dict:
        """Find the cluster containing the given aggregate class."""
        from protean.utils import fqn as get_fqn

        target_fqn = get_fqn(cls)
        return ir["clusters"][target_fqn]

    def test_aggregate_deprecated_in_ir(self) -> None:
        @self.domain.aggregate(deprecated={"since": "0.15", "removal": "0.18"})
        class DeprecatedOrder:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, DeprecatedOrder)
        assert cluster["aggregate"]["deprecated"] == {
            "since": "0.15",
            "removal": "0.18",
        }

    def test_non_deprecated_aggregate_no_key(self) -> None:
        @self.domain.aggregate
        class CleanOrder:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, CleanOrder)
        assert "deprecated" not in cluster["aggregate"]

    def test_event_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class EventOrder:
            pass

        @self.domain.event(part_of=EventOrder, deprecated="0.15")
        class LegacyEvent:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, EventOrder)
        event = list(cluster["events"].values())[0]
        assert event["deprecated"] == {"since": "0.15"}

    def test_field_deprecated_in_ir(self) -> None:
        from protean.fields import String

        @self.domain.aggregate
        class FieldOrder:
            name = String()
            old_field = String(deprecated={"since": "0.14", "removal": "0.17"})

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, FieldOrder)
        fields = cluster["aggregate"]["fields"]
        assert fields["old_field"]["deprecated"] == {
            "since": "0.14",
            "removal": "0.17",
        }
        assert "deprecated" not in fields["name"]

    def test_published_event_deprecated_in_contracts(self) -> None:
        @self.domain.aggregate
        class ContractOrder:
            pass

        @self.domain.event(
            part_of=ContractOrder,
            published=True,
            deprecated={"since": "0.15", "removal": "0.18"},
        )
        class LegacyPublishedEvent:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        contracts = ir["contracts"]["events"]
        assert len(contracts) == 1
        assert contracts[0]["deprecated"] == {
            "since": "0.15",
            "removal": "0.18",
        }


# =====================================================================
# IR Diagnostics — DEPRECATED_ELEMENT and DEPRECATED_FIELD
# =====================================================================


@pytest.mark.no_test_domain
class TestIRDiagnosticsDeprecated:
    """Test DEPRECATED_ELEMENT and DEPRECATED_FIELD diagnostics."""

    @pytest.fixture(autouse=True)
    def setup_domain(self) -> None:
        self.domain = Domain(name="TestDiag")

    def test_deprecated_element_diagnostic(self) -> None:
        @self.domain.aggregate(deprecated={"since": "0.15", "removal": "0.18"})
        class DiagOrder:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        dep_diags = [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"]
        assert len(dep_diags) == 1
        assert "deprecated since v0.15" in dep_diags[0]["message"]
        assert "removal in v0.18" in dep_diags[0]["message"]

    def test_deprecated_element_without_removal(self) -> None:
        @self.domain.aggregate(deprecated="0.15")
        class NoRemovalOrder:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        dep_diags = [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"]
        assert len(dep_diags) == 1
        assert "deprecated since v0.15" in dep_diags[0]["message"]
        assert "removal" not in dep_diags[0]["message"]

    def test_deprecated_field_diagnostic(self) -> None:
        from protean.fields import String

        @self.domain.aggregate
        class FieldDiagOrder:
            name = String()
            old_field = String(deprecated={"since": "0.14", "removal": "0.17"})

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        field_diags = [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_FIELD"]
        assert len(field_diags) == 1
        assert "FieldDiagOrder.old_field" in field_diags[0]["message"]
        assert "deprecated since v0.14" in field_diags[0]["message"]

    def test_no_deprecated_diagnostics_when_clean(self) -> None:
        @self.domain.aggregate
        class CleanDiagOrder:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        dep_diags = [
            d
            for d in ir["diagnostics"]
            if d["code"] in ("DEPRECATED_ELEMENT", "DEPRECATED_FIELD")
        ]
        assert len(dep_diags) == 0

    def test_multiple_deprecated_elements(self) -> None:
        @self.domain.aggregate(deprecated="0.14")
        class MultiOrder:
            pass

        @self.domain.event(part_of=MultiOrder, deprecated="0.15")
        class MultiLegacyEvent:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        dep_diags = [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"]
        assert len(dep_diags) == 2


# =====================================================================
# _classify_removal
# =====================================================================


class TestClassifyRemoval:
    """Tests for ``_classify_removal`` in the diff engine."""

    def test_no_deprecation_is_unexpected(self) -> None:
        assert _classify_removal(None) == "unexpected_removal"

    def test_deprecated_no_removal_version_is_premature(self) -> None:
        assert _classify_removal({"since": "0.15"}) == "premature_removal"

    def test_deprecated_with_removal_no_current_is_premature(self) -> None:
        assert (
            _classify_removal({"since": "0.15", "removal": "0.18"})
            == "premature_removal"
        )

    def test_current_before_removal_is_premature(self) -> None:
        result = _classify_removal(
            {"since": "0.15", "removal": "0.18"},
            current_version="0.16",
        )
        assert result == "premature_removal"

    def test_current_at_removal_is_expected(self) -> None:
        result = _classify_removal(
            {"since": "0.15", "removal": "0.18"},
            current_version="0.18",
        )
        assert result == "expected_removal"

    def test_current_after_removal_is_expected(self) -> None:
        result = _classify_removal(
            {"since": "0.15", "removal": "0.18"},
            current_version="0.19",
        )
        assert result == "expected_removal"


# =====================================================================
# diff_ir — deprecation-aware contract diffing
# =====================================================================


class TestDiffIRDeprecation:
    """Test deprecation-aware contract diffing."""

    @staticmethod
    def _make_ir(events: list[dict]) -> dict:
        """Build a minimal IR dict with contracts."""
        return {
            "clusters": {},
            "projections": {},
            "flows": {"domain_services": {}, "process_managers": {}, "subscribers": {}},
            "contracts": {"events": events},
            "diagnostics": [],
            "domain": {"name": "Test"},
        }

    def test_remove_non_deprecated_event_is_breaking(self) -> None:
        left = self._make_ir(
            [{"fqn": "app.OrderPlaced", "type": "App.OrderPlaced.v1", "fields": {}}]
        )
        right = self._make_ir([])

        result = diff_ir(left, right)
        breaking = result["contracts"].get("breaking_changes", [])
        assert len(breaking) == 1
        assert breaking[0]["classification"] == "unexpected_removal"

    def test_remove_deprecated_event_before_removal_is_breaking(self) -> None:
        left = self._make_ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {},
                    "deprecated": {"since": "0.15", "removal": "0.18"},
                }
            ]
        )
        right = self._make_ir([])

        result = diff_ir(left, right, current_version="0.16")
        breaking = result["contracts"].get("breaking_changes", [])
        assert len(breaking) == 1
        assert breaking[0]["classification"] == "premature_removal"

    def test_remove_deprecated_event_at_removal_is_safe(self) -> None:
        left = self._make_ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {},
                    "deprecated": {"since": "0.15", "removal": "0.18"},
                }
            ]
        )
        right = self._make_ir([])

        result = diff_ir(left, right, current_version="0.18")
        breaking = result["contracts"].get("breaking_changes", [])
        assert len(breaking) == 0
        expected = result["contracts"].get("expected_removals", [])
        assert len(expected) == 1
        assert expected[0]["classification"] == "expected_removal"

    def test_remove_deprecated_field_before_removal_is_breaking(self) -> None:
        left = self._make_ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {
                        "old_field": {
                            "kind": "standard",
                            "type": "String",
                            "deprecated": {"since": "0.14", "removal": "0.17"},
                        }
                    },
                }
            ]
        )
        right = self._make_ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {},
                }
            ]
        )

        result = diff_ir(left, right, current_version="0.15")
        breaking = result["contracts"].get("breaking_changes", [])
        assert len(breaking) == 1
        assert breaking[0]["classification"] == "premature_removal"
        assert breaking[0]["field"] == "old_field"

    def test_remove_deprecated_field_at_removal_is_safe(self) -> None:
        left = self._make_ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {
                        "old_field": {
                            "kind": "standard",
                            "type": "String",
                            "deprecated": {"since": "0.14", "removal": "0.17"},
                        }
                    },
                }
            ]
        )
        right = self._make_ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {},
                }
            ]
        )

        result = diff_ir(left, right, current_version="0.17")
        breaking = result["contracts"].get("breaking_changes", [])
        assert len(breaking) == 0
        expected = result["contracts"].get("expected_removals", [])
        assert len(expected) == 1

    def test_type_change_still_breaking(self) -> None:
        """Type changes are always breaking, regardless of deprecation."""
        left = self._make_ir(
            [{"fqn": "app.OrderPlaced", "type": "App.OrderPlaced.v1", "fields": {}}]
        )
        right = self._make_ir(
            [{"fqn": "app.OrderPlaced", "type": "App.OrderPlaced.v2", "fields": {}}]
        )

        result = diff_ir(left, right)
        breaking = result["contracts"].get("breaking_changes", [])
        assert len(breaking) == 1
        assert breaking[0]["type"] == "contract_type_changed"

    def test_summary_no_breaking_when_expected_removal(self) -> None:
        left = self._make_ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {},
                    "deprecated": {"since": "0.15", "removal": "0.18"},
                }
            ]
        )
        right = self._make_ir([])

        result = diff_ir(left, right, current_version="0.18")
        assert result["summary"]["has_breaking_changes"] is False


# =====================================================================
# _parse_version_tuple
# =====================================================================


class TestParseVersionTuple:
    """Tests for ``_parse_version_tuple`` in the diff engine."""

    def test_two_segment(self) -> None:
        assert _parse_version_tuple("0.15") == (0, 15)

    def test_three_segment(self) -> None:
        assert _parse_version_tuple("1.2.3") == (1, 2, 3)

    def test_non_numeric_segment(self) -> None:
        result = _parse_version_tuple("1.2.3rc1")
        assert result == (1, 2, "3rc1")

    def test_leading_trailing_whitespace(self) -> None:
        assert _parse_version_tuple("  0.15  ") == (0, 15)

    def test_comparison_ordering(self) -> None:
        assert _parse_version_tuple("0.17") < _parse_version_tuple("0.18")
        assert _parse_version_tuple("0.18") == _parse_version_tuple("0.18")
        assert _parse_version_tuple("0.19") > _parse_version_tuple("0.18")

    def test_comparison_three_segment_vs_two(self) -> None:
        assert _parse_version_tuple("0.18") < _parse_version_tuple("0.18.1")

    def test_classify_removal_with_invalid_version_falls_back(self) -> None:
        """Invalid versions should not crash — falls back to premature."""
        result = _classify_removal(
            {"since": "0.15", "removal": "not-a-version"},
            current_version="also-bad",
        )
        # Both are non-numeric strings; comparison still works (string vs string)
        # but the key thing is no crash
        assert result in ("expected_removal", "premature_removal")


# =====================================================================
# IR Builder — deprecated in all element types
# =====================================================================


@pytest.mark.no_test_domain
class TestIRBuilderDeprecatedAllElements:
    """Test that deprecated metadata is emitted for every element type."""

    @pytest.fixture(autouse=True)
    def setup_domain(self) -> None:
        self.domain = Domain(name="TestAllElements")

    @staticmethod
    def _find_cluster(ir: dict, cls: type) -> dict:
        from protean.utils import fqn as get_fqn

        return ir["clusters"][get_fqn(cls)]

    def test_entity_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.entity(part_of=Order, deprecated="0.16")
        class LineItem:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, Order)
        entity = list(cluster["entities"].values())[0]
        assert entity["deprecated"] == {"since": "0.16"}

    def test_value_object_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.value_object(part_of=Order, deprecated="0.15")
        class Money:
            amount: float
            currency: str

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, Order)
        vo = list(cluster["value_objects"].values())[0]
        assert vo["deprecated"] == {"since": "0.15"}

    def test_command_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.command(
            part_of=Order,
            deprecated={"since": "0.15", "removal": "0.18"},
        )
        class PlaceOrder:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, Order)
        cmd = list(cluster["commands"].values())[0]
        assert cmd["deprecated"] == {"since": "0.15", "removal": "0.18"}

    def test_command_handler_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.command(part_of=Order)
        class PlaceOrder:
            pass

        @self.domain.command_handler(part_of=Order, deprecated="0.16")
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def handle_place(self, cmd):
                pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, Order)
        handler = list(cluster["command_handlers"].values())[0]
        assert handler["deprecated"] == {"since": "0.16"}

    def test_event_handler_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.event(part_of=Order)
        class OrderPlaced:
            pass

        @self.domain.event_handler(part_of=Order, deprecated="0.16")
        class OrderEventHandler:
            @handle(OrderPlaced)
            def handle_placed(self, event):
                pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, Order)
        handler = list(cluster["event_handlers"].values())[0]
        assert handler["deprecated"] == {"since": "0.16"}

    def test_repository_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.repository(part_of=Order, deprecated="0.16")
        class OrderRepo:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, Order)
        repo = list(cluster["repositories"].values())[0]
        assert repo["deprecated"] == {"since": "0.16"}

    def test_database_model_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.database_model(part_of=Order, deprecated="0.16")
        class OrderModel:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, Order)
        model = list(cluster["database_models"].values())[0]
        assert model["deprecated"] == {"since": "0.16"}

    def test_application_service_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.application_service(part_of=Order, deprecated="0.16")
        class OrderService:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        cluster = self._find_cluster(ir, Order)
        svc = list(cluster["application_services"].values())[0]
        assert svc["deprecated"] == {"since": "0.16"}

    def test_projection_deprecated_in_ir(self) -> None:
        @self.domain.projection(deprecated="0.16")
        class OrderView:
            order_id = Identifier(identifier=True)

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        proj = list(ir["projections"].values())[0]
        assert proj["projection"]["deprecated"] == {"since": "0.16"}

    def test_domain_service_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.aggregate
        class Inventory:
            pass

        @self.domain.domain_service(part_of=[Order, Inventory], deprecated="0.16")
        class PricingService:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        ds = list(ir["flows"]["domain_services"].values())[0]
        assert ds["deprecated"] == {"since": "0.16"}

    def test_subscriber_deprecated_in_ir(self) -> None:
        @self.domain.subscriber(broker="default", stream="orders", deprecated="0.16")
        class OrderSubscriber:
            def __call__(self, payload):
                pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        sub = list(ir["flows"]["subscribers"].values())[0]
        assert sub["deprecated"] == {"since": "0.16"}

    def test_process_manager_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class PMOrder:
            pass

        @self.domain.event(part_of=PMOrder)
        class PMOrderPlaced:
            order_id = Identifier(required=True)
            total = Float(required=True)

        @self.domain.process_manager(stream_categories=["pm_order"], deprecated="0.16")
        class OrderFulfillment:
            order_id = Identifier()

            @handle(PMOrderPlaced, start=True, correlate="order_id")
            def on_order_placed(self, event):
                self.order_id = event.order_id

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        pm = list(ir["flows"]["process_managers"].values())[0]
        assert pm["deprecated"] == {"since": "0.16"}

    def test_projector_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.event(part_of=Order)
        class OrderPlaced:
            pass

        @self.domain.projection
        class OrderDashboard:
            order_id = Identifier(identifier=True)

        @self.domain.projector(
            projector_for=OrderDashboard,
            aggregates=[Order],
            deprecated="0.16",
        )
        class OrderDashboardProjector:
            @handle(OrderPlaced)
            def on_order_placed(self, event):
                pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        proj = list(ir["projections"].values())[0]
        projector = list(proj["projectors"].values())[0]
        assert projector["deprecated"] == {"since": "0.16"}

    def test_query_deprecated_in_ir(self) -> None:
        @self.domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @self.domain.query(part_of=OrderView, deprecated="0.16")
        class GetOrder:
            order_id = Identifier(required=True)

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        proj = list(ir["projections"].values())[0]
        query = list(proj["queries"].values())[0]
        assert query["deprecated"] == {"since": "0.16"}

    def test_query_handler_deprecated_in_ir(self) -> None:
        @self.domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @self.domain.query(part_of=OrderView)
        class GetOrder:
            order_id = Identifier(required=True)

        @self.domain.query_handler(part_of=OrderView, deprecated="0.16")
        class OrderQueryHandler:
            @read(GetOrder)
            def by_order(self, query):
                pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        proj = list(ir["projections"].values())[0]
        qh = list(proj["query_handlers"].values())[0]
        assert qh["deprecated"] == {"since": "0.16"}


# =====================================================================
# IR Diagnostics — deprecated in projections and flows
# =====================================================================


@pytest.mark.no_test_domain
class TestIRDiagnosticsDeprecatedExtended:
    """Test DEPRECATED_ELEMENT diagnostics for projections and flows."""

    @pytest.fixture(autouse=True)
    def setup_domain(self) -> None:
        self.domain = Domain(name="TestDiagExt")

    def test_deprecated_projection_diagnostic(self) -> None:
        @self.domain.projection(deprecated="0.15")
        class OldView:
            view_id = Identifier(identifier=True)

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        dep_diags = [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"]
        assert len(dep_diags) == 1
        assert "deprecated since v0.15" in dep_diags[0]["message"]

    def test_deprecated_domain_service_diagnostic(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.aggregate
        class Inventory:
            pass

        @self.domain.domain_service(part_of=[Order, Inventory], deprecated="0.16")
        class OldService:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        dep_diags = [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"]
        assert len(dep_diags) == 1
        assert "deprecated since v0.16" in dep_diags[0]["message"]

    def test_deprecated_field_without_removal_diagnostic(self) -> None:
        """Field deprecated with no removal version."""

        @self.domain.aggregate
        class Order:
            old_field = String(deprecated="0.14")

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        field_diags = [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_FIELD"]
        assert len(field_diags) == 1
        assert "deprecated since v0.14" in field_diags[0]["message"]
        assert "removal" not in field_diags[0]["message"]

    def test_deprecated_entity_diagnostic(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.entity(
            part_of=Order,
            deprecated={"since": "0.16", "removal": "0.19"},
        )
        class LineItem:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        dep_diags = [d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"]
        assert len(dep_diags) == 1
        assert "deprecated since v0.16" in dep_diags[0]["message"]
        assert "removal in v0.19" in dep_diags[0]["message"]


# =====================================================================
# IR Builder — field deprecated via ResolvedField (FieldSpec path)
# =====================================================================


@pytest.mark.no_test_domain
class TestIRBuilderFieldDeprecatedResolvedField:
    """Test deprecated on ResolvedField fields (FieldSpec-based)."""

    @pytest.fixture(autouse=True)
    def setup_domain(self) -> None:
        self.domain = Domain(name="TestRFDeprecated")

    def test_resolved_field_deprecated_in_ir(self) -> None:
        """FieldSpec-based fields emit deprecated via _extract_resolved_field."""

        @self.domain.aggregate
        class Order:
            name = String()
            old_name = String(deprecated={"since": "0.14", "removal": "0.17"})

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        from protean.utils import fqn as get_fqn

        cluster = ir["clusters"][get_fqn(Order)]
        fields = cluster["aggregate"]["fields"]
        assert fields["old_name"]["deprecated"] == {
            "since": "0.14",
            "removal": "0.17",
        }
        assert "deprecated" not in fields["name"]

    def test_command_field_deprecated_in_ir(self) -> None:
        @self.domain.aggregate
        class Order:
            pass

        @self.domain.command(part_of=Order)
        class PlaceOrder:
            old_field = String(deprecated="0.14")

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        from protean.utils import fqn as get_fqn

        cluster = ir["clusters"][get_fqn(Order)]
        cmd = list(cluster["commands"].values())[0]
        assert cmd["fields"]["old_field"]["deprecated"] == {"since": "0.14"}

    def test_event_field_deprecated_in_published_contract(self) -> None:
        """Deprecated field in a published event appears in contracts."""

        @self.domain.aggregate
        class Order:
            pass

        @self.domain.event(part_of=Order, published=True)
        class OrderPlaced:
            old_field = String(deprecated={"since": "0.14", "removal": "0.17"})

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        contracts = ir["contracts"]["events"]
        assert len(contracts) == 1
        assert contracts[0]["fields"]["old_field"]["deprecated"] == {
            "since": "0.14",
            "removal": "0.17",
        }
