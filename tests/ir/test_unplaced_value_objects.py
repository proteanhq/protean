"""The top-level ``value_objects`` IR section: value objects no cluster places.

Covers the builder section, schema validation, the three schema generators,
the written schema tree, ``protean ir diff`` and ``classify_changes``, the
clash error, abstract and unheld value objects, and the two ``protean check``
findings that read the section.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from typer.testing import CliRunner

from protean import Domain
from protean._deprecation import RemovedInProtean020Warning
from protean.cli import app
from protean.core.aggregate import BaseAggregate
from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, List, String, ValueObject
from protean.ir import SCHEMA_PATH
from protean.ir.diff import classify_changes, diff_ir
from protean.ir.generators.avro import generate_avro_schemas
from protean.ir.generators.protobuf import generate_proto_schemas
from protean.ir.generators.schema import _build_flat_elements, generate_schemas
from protean.ir.generators.schema_writer import write_all_schemas, write_schemas
from protean.utils import fqn
from tests.ir.support import unplaced_geo
from tests.ir.support.unplaced_addresses import billing, shipping
from tests.ir.test_schema_formats import (
    CustomerCard,
    CustomerReport,
    Dimensions,
    Order,
    Package,
    ShippingAddress,
    _assert_valid_proto_tree,
)

pytestmark = pytest.mark.no_test_domain

runner = CliRunner()

SHIPPING_FQN = fqn(ShippingAddress)


def _ir(*elements: type, **options: Any) -> dict[str, Any]:
    """Return the IR of a domain that registers *elements* in order."""
    domain = Domain(name="Unplaced", root_path=".")
    for element in elements:
        domain.register(element, **options.get(element.__name__, {}))
    domain.init(traverse=False)
    with domain.domain_context():
        return domain.to_ir()


def _projection_only_ir() -> dict[str, Any]:
    return _ir(ShippingAddress, CustomerCard, CustomerReport)


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


def _address_ir(**fields: Any) -> dict[str, Any]:
    """Return the IR of a ``ShippingAddress`` with *fields*, held only by a
    projection. Every call gives the classes the same FQNs, so two IRs diff
    the same value object."""
    address = type(
        "ShippingAddress",
        (BaseValueObject,),
        {"__module__": "app.addresses", "__qualname__": "ShippingAddress", **fields},
    )
    card = type(
        "CustomerCard",
        (BaseProjection,),
        {
            "__module__": "app.cards",
            "__qualname__": "CustomerCard",
            "customer_id": Identifier(identifier=True),
            "address": ValueObject(address),
        },
    )
    return _ir(address, card)


def _schema_files(tmp_path: Path) -> list[str]:
    return sorted(
        p.relative_to(tmp_path / "schemas").as_posix()
        for p in (tmp_path / "schemas").rglob("*")
        if p.is_file()
    )


class TestBuilderSection:
    def test_projection_only_value_object_has_an_entry(self):
        ir = _projection_only_ir()

        assert list(ir["value_objects"]) == [SHIPPING_FQN]
        entry = ir["value_objects"][SHIPPING_FQN]
        assert entry["fields"]["city"]["type"] == "String"
        assert "part_of" in entry
        assert entry["part_of"] is None
        assert entry["element_type"] == "VALUE_OBJECT"
        assert ir["clusters"] == {}

    def test_ir_validates_against_the_schema(self):
        jsonschema.validate(_projection_only_ir(), _schema())

    def test_entry_without_fields_fails_validation(self):
        ir = _projection_only_ir()
        del ir["value_objects"][SHIPPING_FQN]["fields"]

        with pytest.raises(jsonschema.ValidationError, match="'fields'"):
            jsonschema.validate(ir, _schema())

    def test_entry_without_part_of_fails_validation(self):
        ir = _projection_only_ir()
        del ir["value_objects"][SHIPPING_FQN]["part_of"]

        with pytest.raises(jsonschema.ValidationError, match="'part_of'"):
            jsonschema.validate(ir, _schema())

    def test_domain_whose_value_objects_have_a_cluster_has_no_section(self, tmp_path):
        ir = _ir(
            Order,
            Package,
            Dimensions,
            Package={"part_of": Order},
            Dimensions={"part_of": Order},
        )

        assert fqn(Dimensions) in ir["clusters"][fqn(Order)]["value_objects"]
        assert "value_objects" not in ir
        write_all_schemas(ir, tmp_path)
        assert (tmp_path / "schemas" / "Order").is_dir()
        assert not (tmp_path / "schemas" / "value_objects").exists()

    def test_placed_value_object_is_not_in_the_section(self):
        class Holder(BaseAggregate):
            address = ValueObject(ShippingAddress)

        ir = _ir(Holder, ShippingAddress, CustomerCard)

        assert SHIPPING_FQN in ir["clusters"][fqn(Holder)]["value_objects"]
        assert "value_objects" not in ir

    def test_section_and_cluster_keys_are_disjoint(self):
        class Holder(BaseAggregate):
            label = String()

        ir = _ir(
            Holder,
            Dimensions,
            ShippingAddress,
            CustomerCard,
            Dimensions={"part_of": Holder},
        )

        cluster_vos = set(ir["clusters"][fqn(Holder)]["value_objects"])
        assert cluster_vos == {fqn(Dimensions)}
        assert set(ir["value_objects"]) == {SHIPPING_FQN}
        flat = _build_flat_elements(ir)
        assert cluster_vos | set(ir["value_objects"]) <= set(flat)

    def test_abstract_value_object_is_left_out(self):
        class Base(BaseValueObject):
            label = String()

        ir = _ir(Base, ShippingAddress, CustomerCard, Base={"abstract": True})

        assert list(ir["value_objects"]) == [SHIPPING_FQN]

    def test_internal_value_object_is_left_out(self):
        class Tracker(BaseValueObject):
            label = String()

        ir = _ir(Tracker, ShippingAddress, CustomerCard, Tracker={"internal": True})

        assert list(ir["value_objects"]) == [SHIPPING_FQN]

    def test_list_only_value_object_is_in_the_section(self):
        class Tag(BaseValueObject):
            label = String()

        class Holder(BaseAggregate):
            tags = List(content_type=ValueObject(Tag))

        ir = _ir(Holder, Tag)

        assert fqn(Tag) not in ir["clusters"][fqn(Holder)]["value_objects"]
        assert list(ir["value_objects"]) == [fqn(Tag)]
        assert ir["value_objects"][fqn(Tag)]["fields"]["label"]["type"] == "String"

    def test_unheld_value_object_is_in_the_section(self, tmp_path):
        ir = _ir(ShippingAddress)

        assert list(ir["value_objects"]) == [SHIPPING_FQN]
        assert ir["value_objects"][SHIPPING_FQN]["fields"]["city"]["type"] == "String"
        write_all_schemas(ir, tmp_path)
        assert _schema_files(tmp_path) == [
            "value_objects/ShippingAddress.v1.avsc",
            "value_objects/ShippingAddress.v1.json",
            "value_objects/ShippingAddress.v1.proto",
        ]


class TestGenerators:
    def test_json_schema_defines_the_value_object_with_its_fields(self):
        schemas = generate_schemas(_projection_only_ir())

        card = schemas[fqn(CustomerCard)]
        assert "city" in card["$defs"]["ShippingAddress"]["properties"]
        assert "city" in schemas[SHIPPING_FQN]["properties"]

    def test_avro_record_carries_the_fields_and_module_namespace(self):
        schemas = generate_avro_schemas(_projection_only_ir())

        card = schemas[fqn(CustomerCard)]
        address = next(f for f in card["fields"] if f["name"] == "address")
        record = next(t for t in address["type"] if isinstance(t, dict))
        assert [f["name"] for f in record["fields"]] == ["city"]
        assert record["namespace"] == ShippingAddress.__module__

    def test_protobuf_message_carries_the_fields(self):
        with pytest.warns(RemovedInProtean020Warning):
            schemas = generate_proto_schemas(_projection_only_ir())

        card = schemas[fqn(CustomerCard)]
        message = card[card.index("message ShippingAddress {") :]
        assert "optional string city = 1;" in message.split("}")[0]

    def test_nested_value_object_in_the_section(self):
        ir = _ir(
            unplaced_geo.Geo, unplaced_geo.ShippingAddress, unplaced_geo.CustomerCard
        )
        geo_fqn = fqn(unplaced_geo.Geo)
        address_fqn = fqn(unplaced_geo.ShippingAddress)

        assert set(ir["value_objects"]) == {geo_fqn, address_fqn}
        assert ir["value_objects"][geo_fqn]["fields"]["lat"]["type"] == "Float"
        assert ir["value_objects"][address_fqn]["fields"]["geo"] == {
            "kind": "value_object",
            "target": geo_fqn,
        }

        card_json = generate_schemas(ir)[fqn(unplaced_geo.CustomerCard)]
        assert "lat" in card_json["$defs"]["Geo"]["properties"]

        card_avro = generate_avro_schemas(ir)[fqn(unplaced_geo.CustomerCard)]
        address = next(f for f in card_avro["fields"] if f["name"] == "address")
        address_record = next(t for t in address["type"] if isinstance(t, dict))
        geo = next(f for f in address_record["fields"] if f["name"] == "geo")
        geo_record = next(t for t in geo["type"] if isinstance(t, dict))
        assert [f["name"] for f in geo_record["fields"]] == ["lat"]

    def test_nested_value_object_gets_its_own_proto_file(self, tmp_path):
        ir = _ir(
            unplaced_geo.Geo, unplaced_geo.ShippingAddress, unplaced_geo.CustomerCard
        )

        write_all_schemas(ir, tmp_path)
        _assert_valid_proto_tree(tmp_path / "schemas")
        schemas = tmp_path / "schemas"
        geo = (schemas / "value_objects/Geo.v1.proto").read_text()
        assert "  optional double lat = 1;" in geo
        address = (schemas / "value_objects/ShippingAddress.v1.proto").read_text()
        assert 'import "value_objects/Geo.v1.proto";' in address


class TestSchemaTree:
    def test_value_object_files_are_written_and_imported(self, tmp_path):
        write_all_schemas(_projection_only_ir(), tmp_path)

        files = _assert_valid_proto_tree(tmp_path / "schemas")
        vo_files = [
            f for f in _schema_files(tmp_path) if f.startswith("value_objects/")
        ]
        assert vo_files == [
            "value_objects/ShippingAddress.v1.avsc",
            "value_objects/ShippingAddress.v1.json",
            "value_objects/ShippingAddress.v1.proto",
        ]
        proto = (
            tmp_path / "schemas/value_objects/ShippingAddress.v1.proto"
        ).read_text()
        assert "  optional string city = 1;" in proto

        for projection in ("CustomerCard", "CustomerReport"):
            path = f"projections/{projection}.v1.proto"
            assert files[path]["imports"] == ["value_objects/ShippingAddress.v1.proto"]
            assert files[path]["messages"] == [projection]

    @pytest.mark.parametrize(
        ("fmt", "ext"),
        [("json", "json"), ("avro", "avsc"), ("protobuf", "proto")],
    )
    def test_two_unplaced_value_objects_with_one_name_clash(self, tmp_path, fmt, ext):
        ir = _ir(
            billing.Address,
            billing.BillingCard,
            shipping.Address,
            shipping.ShippingCard,
        )
        assert set(ir["value_objects"]) == {fqn(billing.Address), fqn(shipping.Address)}

        with pytest.raises(ValueError) as exc:
            write_schemas(ir, tmp_path, fmt=fmt)

        message = str(exc.value)
        assert f"value_objects/Address.v1.{ext}" in message
        assert fqn(billing.Address) in message
        assert fqn(shipping.Address) in message


def _change(report, change_type: str, element: str):
    changes = [
        c
        for c in [*report.breaking_changes, *report.safe_changes]
        if c.change_type == change_type and c.element_fqn == element
    ]
    assert len(changes) == 1, changes
    return changes[0]


class TestDiff:
    ADDRESS = "app.addresses.ShippingAddress"

    def test_added_field_is_a_safe_change(self):
        left = _address_ir(city=String())
        right = _address_ir(city=String(), country=String())

        assert left["checksum"] != right["checksum"]
        result = diff_ir(left, right)
        changed = result["value_objects"]["changed"][self.ADDRESS]
        assert "country" in changed["fields"]["added"]
        assert result["summary"]["has_changes"] is True
        assert result["summary"]["counts"]["changed"] == 1

        report = classify_changes(result, left, right)
        assert _change(report, "optional_field_added", self.ADDRESS).severity == "safe"
        assert not report.is_breaking

    def test_removed_field_is_a_breaking_change(self):
        left = _address_ir(city=String())
        right = _address_ir()

        result = diff_ir(left, right)
        assert (
            "city"
            in result["value_objects"]["changed"][self.ADDRESS]["fields"]["removed"]
        )
        report = classify_changes(result, left, right)
        assert _change(report, "field_removed", self.ADDRESS).severity == "breaking"

    def test_added_and_removed_entries_are_classified(self):
        left = _address_ir(city=String())
        right = copy.deepcopy(left)
        right["value_objects"]["app.addresses.Extra"] = {
            **right["value_objects"][self.ADDRESS],
            "fqn": "app.addresses.Extra",
            "name": "Extra",
        }

        added = diff_ir(left, right)
        assert added["summary"]["counts"]["added"] == 1
        report = classify_changes(added, left, right)
        assert (
            _change(report, "element_added", "app.addresses.Extra").severity == "safe"
        )

        removed = diff_ir(right, left)
        assert removed["summary"]["counts"]["removed"] == 1
        report = classify_changes(removed, right, left)
        assert (
            _change(report, "element_removed", "app.addresses.Extra").severity
            == "breaking"
        )

    def test_move_out_of_a_cluster_is_removed_and_added(self):
        def holder_ir(**fields: Any) -> dict[str, Any]:
            holder = type(
                "Holder",
                (BaseAggregate,),
                {"__module__": "app.holders", "__qualname__": "Holder", **fields},
            )
            return _ir(holder, ShippingAddress, CustomerCard)

        left = holder_ir(address=ValueObject(ShippingAddress))
        right = holder_ir(label=String())
        assert SHIPPING_FQN in left["clusters"]["app.holders.Holder"]["value_objects"]
        assert "value_objects" not in left
        assert list(right["value_objects"]) == [SHIPPING_FQN]

        result = diff_ir(left, right)
        cluster_vos = result["clusters"]["changed"]["app.holders.Holder"]
        assert SHIPPING_FQN in cluster_vos["value_objects"]["removed"]
        assert SHIPPING_FQN in result["value_objects"]["added"]

        report = classify_changes(result, left, right)
        moves = sorted(
            (c.change_type, c.severity)
            for c in [*report.breaking_changes, *report.safe_changes]
            if c.element_fqn == SHIPPING_FQN
        )
        assert moves == [("element_added", "safe"), ("element_removed", "breaking")]

    def test_deprecation_check_reads_the_section(self):
        left = _address_ir(city=String())
        right = copy.deepcopy(left)
        right["value_objects"][self.ADDRESS]["deprecated"] = {
            "since": 0.15,
            "removal": "0.18",
        }

        with pytest.raises(ConfigurationError, match="ShippingAddress"):
            diff_ir(left, right)

    @pytest.mark.parametrize(
        ("right_fields", "exit_code"),
        [({"city": String(), "country": String()}, 3), ({}, 1)],
        ids=["field-added", "field-removed"],
    )
    def test_cli_prints_the_section_and_exits(self, tmp_path, right_fields, exit_code):
        left = tmp_path / "left.json"
        right = tmp_path / "right.json"
        left.write_text(json.dumps(_address_ir(city=String())))
        right.write_text(json.dumps(_address_ir(**right_fields)))

        result = runner.invoke(
            app, ["ir", "diff", "--left", str(left), "--right", str(right)]
        )

        assert result.exit_code == exit_code, result.output
        output = result.output.replace("\n", "")
        assert "Value Objects" in output
        assert "ShippingAddress" in output


def _diagnostics(ir: dict[str, Any], code: str) -> list[dict[str, Any]]:
    return [d for d in ir["diagnostics"] if d["code"] == code]


class TestCheckFindings:
    def test_mutable_field_on_an_unplaced_value_object(self):
        class Tags(BaseValueObject):
            labels = List()

        ir = _ir(Tags)

        assert fqn(Tags) in ir["value_objects"]
        findings = _diagnostics(ir, "VALUE_OBJECT_MUTABLE_FIELD")
        assert [(d["element"], d["field"]) for d in findings] == [(fqn(Tags), "labels")]

    def test_deprecated_unplaced_value_object(self):
        class OldAddress(BaseValueObject):
            city = String()

        ir = _ir(OldAddress, OldAddress={"deprecated": {"since": "0.15"}})

        assert fqn(OldAddress) in ir["value_objects"]
        findings = _diagnostics(ir, "DEPRECATED_ELEMENT")
        assert [d["element"] for d in findings] == [fqn(OldAddress)]

    def test_placed_value_object_gets_each_finding_once(self):
        class Holder(BaseAggregate):
            label = String()

        class Tags(BaseValueObject):
            labels = List()

        ir = _ir(
            Holder,
            Tags,
            Tags={"part_of": Holder, "deprecated": {"since": "0.15"}},
        )

        assert "value_objects" not in ir
        mutable = _diagnostics(ir, "VALUE_OBJECT_MUTABLE_FIELD")
        assert [d["element"] for d in mutable] == [fqn(Tags)]
        deprecated = _diagnostics(ir, "DEPRECATED_ELEMENT")
        assert [d["element"] for d in deprecated] == [fqn(Tags)]
