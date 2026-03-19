"""Tests for deprecation support in domain elements, fields, IR, and diff."""

from __future__ import annotations

import pytest

from protean import Domain
from protean.exceptions import ConfigurationError
from protean.fields import String
from protean.ir.builder import IRBuilder
from protean.ir.diff import _classify_removal, diff_ir
from protean.utils import _normalize_deprecated


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
        assert extra.get("deprecated") == {"since": "0.15", "removal": "0.18"}

    def test_fieldspec_not_deprecated_no_extra(self) -> None:
        from protean.fields.spec import FieldSpec

        fs = FieldSpec(str)
        kwargs = fs.resolve_field_kwargs()
        extra = kwargs.get("json_schema_extra", {})
        assert "deprecated" not in extra


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

        dep_diags = [
            d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"
        ]
        assert len(dep_diags) == 1
        assert "deprecated since v0.15" in dep_diags[0]["message"]
        assert "removal in v0.18" in dep_diags[0]["message"]

    def test_deprecated_element_without_removal(self) -> None:
        @self.domain.aggregate(deprecated="0.15")
        class NoRemovalOrder:
            pass

        self.domain.init(traverse=False)
        ir = IRBuilder(self.domain).build()

        dep_diags = [
            d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"
        ]
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

        field_diags = [
            d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_FIELD"
        ]
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

        dep_diags = [
            d for d in ir["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"
        ]
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
