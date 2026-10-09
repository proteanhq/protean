"""The ``Decimal`` IR type: builder output, schema validation, generators, diff."""

from __future__ import annotations

import decimal
import json
import re
from typing import Any

import jsonschema
import pytest

from protean import Domain
from protean.fields import Custom, Decimal, Float, List, String
from protean.ir import SCHEMA_PATH
from protean.ir.builder import IRBuilder
from protean.ir.diff import classify_changes, diff_ir
from protean.ir.generators.avro import generate_avro_schema
from protean.ir.generators.protobuf import generate_proto_schema
from protean.ir.generators.schema import DECIMAL_PATTERN, generate_element_schema

pytestmark = pytest.mark.no_test_domain

_V020_SCHEMA = SCHEMA_PATH.parent.parent / "v0.2.0" / "schema.json"


def _build(**fields: Any) -> dict[str, Any]:
    """Build the IR of a domain with one aggregate ``Account`` holding *fields*."""
    domain = Domain(name="Decimals")
    account = type("Account", (), {"__module__": __name__, **fields})
    domain.aggregate(account)
    domain.init(traverse=False)
    return IRBuilder(domain).build()


def _aggregate(ir: dict[str, Any]) -> dict[str, Any]:
    clusters = list(ir["clusters"].values())
    assert len(clusters) == 1
    return clusters[0]["aggregate"]


def _field(ir: dict[str, Any], name: str) -> dict[str, Any]:
    return _aggregate(ir)["fields"][name]


class TestBuilder:
    def test_precision_and_scale_are_recorded(self):
        ir = _build(x=Decimal(precision=19, scale=4), y=Float())

        assert _field(ir, "x") == {
            "kind": "standard",
            "type": "Decimal",
            "precision": 19,
            "scale": 4,
        }
        assert _field(ir, "y") == {"kind": "standard", "type": "Float"}
        jsonschema.validate(ir, json.loads(SCHEMA_PATH.read_text()))

    def test_bare_decimal_carries_neither_key(self):
        ir = _build(x=Decimal())

        assert _field(ir, "x") == {"kind": "standard", "type": "Decimal"}

    def test_precision_alone_is_recorded_alone(self):
        ir = _build(x=Decimal(precision=10))

        assert _field(ir, "x") == {
            "kind": "standard",
            "type": "Decimal",
            "precision": 10,
        }

    def test_custom_decimal_records_decimal(self):
        ir = _build(x=Custom(decimal.Decimal))

        assert _field(ir, "x") == {"kind": "custom", "type": "Decimal"}

    def test_other_numeric_and_string_fields_carry_no_precision(self):
        ir = _build(f=Float(max_value=10), s=String(max_length=20))

        for name in ("f", "s"):
            entry = _field(ir, name)
            assert entry["type"] in ("Float", "String")
            assert "precision" not in entry
            assert "scale" not in entry

    def test_python_type_name_reads_the_explicit_map_entry(self):
        class Money(decimal.Decimal):
            pass

        # A subclass misses the map and falls back to its own ``__name__``, so
        # ``decimal.Decimal`` resolving to "Decimal" comes from the map entry.
        assert IRBuilder._python_type_name(Money) == "Money"
        assert IRBuilder._python_type_name(decimal.Decimal) == "Decimal"

    def test_list_of_decimals_has_decimal_content_type(self):
        ir = _build(prices=List(content_type=Decimal))

        assert _field(ir, "prices")["content_type"] == "Decimal"


class TestSchemaValidation:
    def test_string_precision_fails_validation(self):
        ir = _build(x=Decimal(precision=19, scale=4))
        _field(ir, "x")["precision"] = "19"

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ir, json.loads(SCHEMA_PATH.read_text()))

    def test_previous_schema_rejects_the_decimal_type(self):
        ir = _build(x=Decimal())
        ir["ir_version"] = "0.2.0"

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ir, json.loads(_V020_SCHEMA.read_text()))


class TestJsonSchemaGenerator:
    def test_decimal_with_precision_and_scale(self):
        ir = _build(x=Decimal(precision=19, scale=4, required=True))

        schema = generate_element_schema(_aggregate(ir))

        assert schema["properties"]["x"] == {
            "pattern": DECIMAL_PATTERN,
            "type": "string",
            "x-precision": 19,
            "x-scale": 4,
        }

    def test_bare_decimal_has_no_precision_keys(self):
        ir = _build(x=Decimal(required=True))

        schema = generate_element_schema(_aggregate(ir))

        assert schema["properties"]["x"] == {
            "pattern": DECIMAL_PATTERN,
            "type": "string",
        }

    def test_numeric_bounds_are_left_off_a_decimal(self):
        ir = _build(x=Decimal(min_value=0, max_value=100, required=True))
        assert _field(ir, "x")["max_value"] == 100

        prop = generate_element_schema(_aggregate(ir))["properties"]["x"]

        assert "maximum" not in prop
        assert "minimum" not in prop

    def test_list_items_use_the_decimal_mapping(self):
        ir = _build(prices=List(content_type=Decimal, required=True))

        prop = generate_element_schema(_aggregate(ir))["properties"]["prices"]

        assert prop["items"] == {"pattern": DECIMAL_PATTERN, "type": "string"}

    @pytest.mark.parametrize(
        "value",
        ["12.5000", "-3.25", "0", "0.00", "100", "1E+2", "0E-8", "-1.5E-7"],
    )
    def test_pattern_accepts_what_the_payload_encoder_writes(self, value):
        domain = Domain(name="Payload")

        @domain.aggregate
        class Wallet:
            amount = Decimal()

        domain.init(traverse=False)
        with domain.domain_context():
            payload = Wallet(amount=decimal.Decimal(value)).to_dict()

        encoded = payload["amount"]
        assert encoded == str(decimal.Decimal(value))
        assert re.fullmatch(DECIMAL_PATTERN, encoded)

    @pytest.mark.parametrize("value", ["abc", "1.", ".5", "1,000", "NaN", ""])
    def test_pattern_rejects_non_numbers(self, value):
        assert re.fullmatch(DECIMAL_PATTERN, value) is None


class TestAvroGenerator:
    def _avro_field(self, ir: dict[str, Any], name: str) -> Any:
        fields = generate_avro_schema(_aggregate(ir))["fields"]
        matches = [f for f in fields if f["name"] == name]
        assert len(matches) == 1
        return matches[0]["type"]

    def test_decimal_with_precision_uses_the_logical_type(self):
        ir = _build(x=Decimal(precision=19, scale=4, required=True))

        assert self._avro_field(ir, "x") == {
            "type": "bytes",
            "logicalType": "decimal",
            "precision": 19,
            "scale": 4,
        }

    def test_scale_defaults_to_zero(self):
        ir = _build(x=Decimal(precision=5, required=True))

        assert self._avro_field(ir, "x") == {
            "type": "bytes",
            "logicalType": "decimal",
            "precision": 5,
            "scale": 0,
        }

    def test_decimal_without_precision_is_a_string(self):
        ir = _build(x=Decimal(scale=2, required=True))

        assert self._avro_field(ir, "x") == "string"

    def test_optional_decimal_is_wrapped_in_a_null_union(self):
        ir = _build(x=Decimal(precision=19, scale=4))

        assert self._avro_field(ir, "x") == [
            "null",
            {"type": "bytes", "logicalType": "decimal", "precision": 19, "scale": 4},
        ]

    def test_list_of_decimals_has_string_items(self):
        ir = _build(prices=List(content_type=Decimal, required=True))

        assert self._avro_field(ir, "prices") == {"type": "array", "items": "string"}


class TestProtobufGenerator:
    def test_decimal_is_a_string(self):
        ir = _build(x=Decimal(precision=19, scale=4, required=True))

        proto = generate_proto_schema(_aggregate(ir))

        assert re.search(r"^\s*string x = \d+;$", proto, re.MULTILINE), proto


def _report(left: dict[str, Any], right: dict[str, Any]):
    return classify_changes(diff_ir(left, right), left, right)


def _kinds(changes: list[Any]) -> list[str]:
    return [c.change_type for c in changes]


class TestDiff:
    def test_float_to_decimal_is_a_breaking_type_change(self):
        report = _report(_build(x=Float()), _build(x=Decimal(precision=19, scale=4)))

        assert _kinds(report.breaking_changes) == ["field_type_changed"]
        assert report.safe_changes == []

    def test_raising_precision_is_a_safe_widening(self):
        report = _report(
            _build(x=Decimal(precision=10, scale=2)),
            _build(x=Decimal(precision=19, scale=2)),
        )

        assert report.breaking_changes == []
        assert _kinds(report.safe_changes) == ["field_precision_widened"]
        change = report.safe_changes[0]
        assert change.message == (
            "Field 'x' precision widened (precision from 10 to 19) "
            f"in AGGREGATE '{change.element_fqn}'"
        )
        assert report.avro_verdict == "NONE"

    def test_removing_precision_is_a_safe_widening(self):
        report = _report(
            _build(x=Decimal(precision=10, scale=2)),
            _build(x=Decimal(scale=2)),
        )

        assert report.breaking_changes == []
        assert _kinds(report.safe_changes) == ["field_precision_widened"]
        assert "(precision from 10 to unset)" in report.safe_changes[0].message

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ({"precision": 19, "scale": 2}, {"precision": 10, "scale": 2}),
            ({"precision": 19, "scale": 2}, {"precision": 19, "scale": 4}),
            ({"scale": 2}, {"precision": 19, "scale": 2}),
            ({"precision": 19, "scale": 2}, {"precision": 19}),
        ],
        ids=["narrowed", "scale-changed", "precision-added", "scale-removed"],
    )
    def test_other_shape_changes_are_breaking(self, left, right):
        report = _report(_build(x=Decimal(**left)), _build(x=Decimal(**right)))

        assert _kinds(report.breaking_changes) == ["field_type_changed"]
        assert report.safe_changes == []
        assert "Decimal shape changed" in report.breaking_changes[0].message

    def test_unchanged_decimal_reports_nothing(self):
        report = _report(
            _build(x=Decimal(precision=19, scale=4)),
            _build(x=Decimal(precision=19, scale=4)),
        )

        assert report.breaking_changes == []
        assert report.safe_changes == []

    def test_a_bound_change_on_a_decimal_is_not_a_shape_change(self):
        report = _report(
            _build(x=Decimal(precision=19, scale=4, max_value=10)),
            _build(x=Decimal(precision=19, scale=4, max_value=20)),
        )

        assert report.breaking_changes == []
        assert report.safe_changes == []

    def test_rename_that_narrows_precision_is_breaking(self):
        report = _report(
            _build(x=Decimal(precision=19, scale=2)),
            _build(amount=Decimal(precision=10, scale=2, renamed_from="x")),
        )

        assert _kinds(report.breaking_changes) == ["field_type_changed"]
        assert "field_renamed" not in _kinds(report.safe_changes)
        assert "(precision from 19 to 10)" in report.breaking_changes[0].message

    def test_rename_that_widens_precision_reports_both(self):
        report = _report(
            _build(x=Decimal(precision=10, scale=2)),
            _build(amount=Decimal(precision=19, scale=2, renamed_from="x")),
        )

        assert report.breaking_changes == []
        assert sorted(_kinds(report.safe_changes)) == [
            "field_precision_widened",
            "field_renamed",
        ]

    def test_rename_that_keeps_the_shape_is_a_plain_rename(self):
        report = _report(
            _build(x=Decimal(precision=19, scale=2)),
            _build(amount=Decimal(precision=19, scale=2, renamed_from="x")),
        )

        assert report.breaking_changes == []
        assert _kinds(report.safe_changes) == ["field_renamed"]
