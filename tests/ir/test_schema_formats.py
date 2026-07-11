"""Tests for IR -> Avro and Protobuf schema emission.

Covers field-type mapping, optional handling (Avro unions / proto3 `optional`),
logical / well-known types, deterministic Protobuf field numbers, per-version
file emission, and an fastavro round-trip parse of the generated Avro.
"""

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Identifier, Integer
from protean.ir.generators.avro import generate_avro_schema
from protean.ir.generators.protobuf import generate_proto_schema
from protean.ir.generators.schema_writer import write_schemas


def _f(type_name: str, **extra: Any) -> dict[str, Any]:
    return {"kind": "standard", "type": type_name, **extra}


def _elem(name: str, fields: dict[str, Any], version: int = 1) -> dict[str, Any]:
    return {
        "element_type": "EVENT",
        "name": name,
        "fqn": f"app.{name}",
        "__version__": version,
        "fields": fields,
    }


class TestAvroMapping:
    def test_scalar_and_logical_types(self):
        schema = generate_avro_schema(
            _elem(
                "E",
                {
                    "id": _f("Identifier", identifier=True),
                    "count": _f("Integer", required=True),
                    "ratio": _f("Float", required=True),
                    "flag": _f("Boolean", required=True),
                    "when": _f("DateTime", required=True),
                    "day": _f("Date", required=True),
                },
            )
        )
        assert schema["type"] == "record"
        assert schema["name"] == "E"
        types = {f["name"]: f["type"] for f in schema["fields"]}
        assert types["id"] == {"type": "string", "logicalType": "uuid"}
        assert types["count"] == "long"
        assert types["ratio"] == "double"
        assert types["flag"] == "boolean"
        assert types["when"] == {"type": "long", "logicalType": "timestamp-millis"}
        assert types["day"] == {"type": "int", "logicalType": "date"}

    def test_optional_is_null_first_union_with_default(self):
        schema = generate_avro_schema(_elem("E", {"note": _f("String")}))
        note = next(f for f in schema["fields"] if f["name"] == "note")
        assert note["type"] == ["null", "string"]
        assert note["default"] is None

    def test_optional_with_non_null_default_still_defaults_to_null(self):
        # Avro requires a union default to match the first branch (null), so a
        # non-null IR default must not leak onto a null-first union.
        schema = generate_avro_schema(
            _elem("E", {"status": _f("String", default="pending")})
        )
        status = next(f for f in schema["fields"] if f["name"] == "status")
        assert status["type"] == ["null", "string"]
        assert status["default"] is None

    def test_required_field_has_no_union(self):
        schema = generate_avro_schema(_elem("E", {"name": _f("String", required=True)}))
        name = next(f for f in schema["fields"] if f["name"] == "name")
        assert name["type"] == "string"
        assert "default" not in name

    def test_renamed_from_emits_aliases(self):
        # A declared rename becomes Avro field aliases so a reader on the new
        # schema resolves data written under the old name (backward-compatible).
        schema = generate_avro_schema(
            _elem(
                "E",
                {"new_name": _f("String", required=True, renamed_from=["old_name"])},
            )
        )
        field = next(f for f in schema["fields"] if f["name"] == "new_name")
        assert field["aliases"] == ["old_name"]

    def test_list_becomes_array(self):
        schema = generate_avro_schema(
            _elem("E", {"tags": {"kind": "list", "type": "List", "required": True}})
        )
        tags = next(f for f in schema["fields"] if f["name"] == "tags")
        assert tags["type"] == {"type": "array", "items": "string"}


class TestAvroRoundTrip:
    def test_generated_schema_parses_with_fastavro(self):
        fastavro = pytest.importorskip("fastavro")
        schema = generate_avro_schema(
            _elem(
                "OrderPlaced",
                {
                    "order_id": _f("Identifier", identifier=True),
                    "qty": _f("Integer", required=True),
                    "note": _f("String"),
                    "when": _f("DateTime"),
                },
            )
        )
        parsed = fastavro.parse_schema(schema)  # raises on an invalid schema
        assert parsed["name"].endswith("OrderPlaced")


class TestProtobufMapping:
    def test_types_labels_and_field_numbers(self):
        proto = generate_proto_schema(
            _elem(
                "E",
                {
                    "aaa": _f("String", required=True),
                    "bbb": _f("Integer"),
                    "ccc": _f("DateTime"),
                },
            )
        )
        assert 'syntax = "proto3";' in proto
        assert 'import "google/protobuf/timestamp.proto";' in proto
        # Numbers assigned 1..N in sorted field-name order.
        assert "  string aaa = 1;" in proto
        assert "  optional int64 bbb = 2;" in proto
        assert "  optional google.protobuf.Timestamp ccc = 3;" in proto

    def test_repeated_for_list(self):
        proto = generate_proto_schema(
            _elem("E", {"tags": {"kind": "list", "type": "List"}})
        )
        assert "  repeated string tags = 1;" in proto

    def test_field_numbers_follow_sorted_name_order(self):
        element = _elem("E", {"z": _f("String"), "a": _f("Integer", required=True)})
        proto = generate_proto_schema(element)
        assert "  int64 a = 1;" in proto
        assert "  optional string z = 2;" in proto

    def test_regenerating_an_unchanged_schema_is_byte_identical(self):
        element = _elem("E", {"z": _f("String"), "a": _f("Integer", required=True)})
        assert generate_proto_schema(element) == generate_proto_schema(element)

    def test_adding_a_field_renumbers_alphabetically_later_fields(self):
        # Documents the emission-only numbering: field numbers are NOT stable
        # across schema evolution (see the changelog / docs caveat). Inserting
        # 'a' shifts every alphabetically-later field's number.
        before = generate_proto_schema(
            _elem("E", {"b": _f("String"), "c": _f("String")})
        )
        after = generate_proto_schema(
            _elem("E", {"a": _f("String"), "b": _f("String"), "c": _f("String")})
        )
        assert "  optional string b = 1;" in before
        assert "  optional string a = 1;" in after  # 'a' claims number 1
        assert "  optional string b = 2;" in after  # 'b' shifted 1 -> 2


class TestSchemaWriterFormats:
    def _ir(self, test_domain):
        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            __version__ = 2
            order_id = Identifier(identifier=True)
            qty = Integer(required=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)
        return test_domain.to_ir()

    @pytest.mark.parametrize("fmt,ext", [("avro", "avsc"), ("protobuf", "proto")])
    def test_per_version_files_written(self, test_domain, tmp_path, fmt, ext):
        ir = self._ir(test_domain)
        written = write_schemas(ir, tmp_path, fmt=fmt)
        assert len(written) > 0
        assert any(str(p).endswith(f"OrderPlaced.v2.{ext}") for p in written)

    def test_unknown_format_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown schema format"):
            write_schemas({}, tmp_path, fmt="yaml")

    def test_non_data_and_fieldless_elements_are_skipped(self, tmp_path):
        # A cluster whose aggregate has no fields, plus no data events.
        ir = {
            "clusters": {
                "app.Empty": {
                    "aggregate": {
                        "element_type": "AGGREGATE",
                        "name": "Empty",
                        "fqn": "app.Empty",
                    }
                }
            },
            "projections": {},
        }
        assert write_schemas(ir, tmp_path, fmt="avro") == []


class TestAvroComplexFields:
    @staticmethod
    def _money():
        return {
            "element_type": "VALUE_OBJECT",
            "name": "Money",
            "fqn": "app.Money",
            "fields": {"amount": _f("Float", required=True)},
        }

    def test_nested_value_object_and_dedup(self):
        order = _elem(
            "Order",
            {
                "total": {"kind": "value_object", "type": "VO", "target": "app.Money"},
                "fee": {"kind": "has_one", "type": "VO", "target": "app.Money"},
            },
        )
        schema = generate_avro_schema(
            order, all_elements={"app.Money": self._money(), "app.Order": order}
        )
        total = next(f for f in schema["fields"] if f["name"] == "total")
        fee = next(f for f in schema["fields"] if f["name"] == "fee")
        # Fields are emitted sorted, so `fee` (first) defines the Money record
        # and `total` (second) references it by fullname (namespace.Name).
        assert fee["type"][1]["type"] == "record"  # ["null", {record}]
        assert fee["type"][1]["name"] == "Money"
        assert total["type"] == ["null", "app.Money"]

    def test_cross_namespace_value_object_referenced_twice_is_valid(self):
        # A shared-kernel value object reused across clusters must be referenced
        # by fullname; a bare short name would resolve against the enclosing
        # namespace and yield an invalid, non-existent type.
        fastavro = pytest.importorskip("fastavro")
        money = {
            "element_type": "VALUE_OBJECT",
            "name": "Money",
            "fqn": "shared.kernel.Money",
            "fields": {"amount": _f("Float", required=True)},
        }
        order = {
            "element_type": "AGGREGATE",
            "name": "Order",
            "fqn": "sales.ordering.Order",
            "fields": {
                "total": {
                    "kind": "value_object",
                    "type": "VO",
                    "target": "shared.kernel.Money",
                },
                "fee": {
                    "kind": "value_object",
                    "type": "VO",
                    "target": "shared.kernel.Money",
                },
            },
        }
        schema = generate_avro_schema(
            order,
            all_elements={
                "shared.kernel.Money": money,
                "sales.ordering.Order": order,
            },
        )
        fastavro.parse_schema(schema)  # must not raise on the second reference
        total = next(f for f in schema["fields"] if f["name"] == "total")
        fee = next(f for f in schema["fields"] if f["name"] == "fee")
        assert fee["type"][1]["namespace"] == "shared.kernel"  # defines record
        assert total["type"] == ["null", "shared.kernel.Money"]  # by fullname

    def test_has_many_and_value_object_list_become_array_of_record(self):
        order = _elem(
            "Order",
            {
                "items": {
                    "kind": "has_many",
                    "type": "List",
                    "target": "app.Money",
                    "required": True,
                }
            },
        )
        schema = generate_avro_schema(
            order, all_elements={"app.Money": self._money(), "app.Order": order}
        )
        items = next(f for f in schema["fields"] if f["name"] == "items")
        assert items["type"]["type"] == "array"
        assert items["type"]["items"]["type"] == "record"

    def test_dict_becomes_map_and_reference_becomes_string(self):
        schema = generate_avro_schema(
            _elem(
                "E",
                {
                    "meta": {"kind": "dict", "type": "Dict", "required": True},
                    "owner": {
                        "kind": "reference",
                        "type": "Reference",
                        "required": True,
                    },
                },
            )
        )
        types = {f["name"]: f["type"] for f in schema["fields"]}
        assert types["meta"] == {"type": "map", "values": "string"}
        assert types["owner"] == "string"

    def test_list_with_content_type(self):
        schema = generate_avro_schema(
            _elem(
                "E",
                {
                    "nums": {
                        "kind": "list",
                        "type": "List",
                        "content_type": "Integer",
                        "required": True,
                    }
                },
            )
        )
        nums = next(f for f in schema["fields"] if f["name"] == "nums")
        assert nums["type"] == {"type": "array", "items": "long"}

    def test_unresolvable_target_falls_back_to_map(self):
        schema = generate_avro_schema(
            _elem("E", {"x": {"kind": "value_object", "type": "VO", "target": ""}})
        )
        x = next(f for f in schema["fields"] if f["name"] == "x")
        assert x["type"] == ["null", {"type": "map", "values": "string"}]


class TestGenerateAllSchemas:
    def test_avro_and_proto_cover_all_data_elements(self, test_domain):
        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)
        ir = test_domain.to_ir()

        from protean.ir.generators.avro import generate_avro_schemas
        from protean.ir.generators.protobuf import generate_proto_schemas

        avro = generate_avro_schemas(ir)
        proto = generate_proto_schemas(ir)
        assert any("OrderPlaced" in k for k in avro)
        assert any("OrderPlaced" in k for k in proto)


class TestSchemaGenerateCLI:
    def test_generate_avro_via_cli(self, test_domain, tmp_path):
        class Order(BaseAggregate):
            order_id = Identifier(identifier=True)

        class OrderPlaced(BaseEvent):
            order_id = Identifier(identifier=True)

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        ir_file = tmp_path / "ir.json"
        ir_file.write_text(json.dumps(test_domain.to_ir()), encoding="utf-8")
        out = tmp_path / "out"

        result = CliRunner().invoke(
            app,
            [
                "schema",
                "generate",
                "--ir",
                str(ir_file),
                "--output",
                str(out),
                "-f",
                "avro",
            ],
        )
        assert result.exit_code == 0
        assert list((out / "schemas").rglob("*.avsc"))

    def test_unknown_format_aborts(self, tmp_path):
        ir_file = tmp_path / "ir.json"
        ir_file.write_text(
            json.dumps({"clusters": {}, "projections": {}}), encoding="utf-8"
        )

        result = CliRunner().invoke(
            app, ["schema", "generate", "--ir", str(ir_file), "-f", "yaml"]
        )
        assert result.exit_code != 0


class TestAvroFieldMetadata:
    def test_increment_default_and_docs(self):
        schema = generate_avro_schema(
            {
                "element_type": "EVENT",
                "name": "E",
                "fqn": "app.E",
                "description": "An event",
                "fields": {
                    "seq": {
                        "kind": "auto",
                        "type": "Auto",
                        "increment": True,
                        "required": True,
                    },
                    "status": _f("String", required=True, default="new"),
                    "note": _f("String", description="a note"),
                },
            }
        )
        assert schema["doc"] == "An event"
        by_name = {f["name"]: f for f in schema["fields"]}
        assert by_name["seq"]["type"] == "long"  # increment -> long
        assert by_name["status"]["default"] == "new"  # required + default
        assert by_name["note"]["doc"] == "a note"  # field description


class TestFlatElementSkips:
    """Fieldless and non-data-carrying flat elements are skipped."""

    def _ir(self):
        return {
            "clusters": {
                "app.C": {
                    "aggregate": {
                        "element_type": "AGGREGATE",
                        "name": "C",
                        "fqn": "app.C",
                        "fields": {"id": _f("Identifier", identifier=True)},
                    },
                    "events": {
                        # Data type but no "fields" -> skipped.
                        "app.NoFields": {
                            "element_type": "EVENT",
                            "name": "NoFields",
                            "fqn": "app.NoFields",
                        },
                        # Non-data element type -> skipped.
                        "app.NotData": {
                            "element_type": "SUBSCRIBER",
                            "name": "NotData",
                            "fqn": "app.NotData",
                            "fields": {"x": _f("String")},
                        },
                    },
                }
            },
            "projections": {},
        }

    def test_generate_avro_schemas_skips(self):
        from protean.ir.generators.avro import generate_avro_schemas

        schemas = generate_avro_schemas(self._ir())
        assert "app.C" in schemas
        assert "app.NoFields" not in schemas
        assert "app.NotData" not in schemas

    def test_generate_proto_schemas_skips(self):
        from protean.ir.generators.protobuf import generate_proto_schemas

        schemas = generate_proto_schemas(self._ir())
        assert "app.C" in schemas
        assert "app.NoFields" not in schemas
        assert "app.NotData" not in schemas

    def test_write_schemas_skips(self, tmp_path):
        written = write_schemas(self._ir(), tmp_path, fmt="avro")
        names = [p.name for p in written]
        assert names == ["C.v1.avsc"]


class TestProtobufComplexFields:
    def test_scalar_increment_reference_and_dict(self):
        # Sorted field order is meta, ref, seq -> numbers 1, 2, 3.
        proto = generate_proto_schema(
            _elem(
                "E",
                {
                    "seq": {
                        "kind": "auto",
                        "type": "Auto",
                        "increment": True,
                        "required": True,
                    },
                    "ref": {"kind": "reference", "type": "Ref"},
                    "meta": {"kind": "dict", "type": "Dict"},
                },
            )
        )
        assert "  map<string, string> meta = 1;" in proto  # map carries no label
        assert "  optional string ref = 2;" in proto  # reference -> string
        assert "  int64 seq = 3;" in proto  # increment auto -> int64

    def test_unresolvable_value_object_target_becomes_map(self):
        proto = generate_proto_schema(
            _elem("E", {"x": {"kind": "value_object", "type": "VO", "target": ""}})
        )
        assert "  map<string, string> x = 1;" in proto

    def test_nested_messages_are_emitted_and_deduped(self):
        currency = {
            "element_type": "VALUE_OBJECT",
            "name": "Currency",
            "fqn": "app.Currency",
            "fields": {"code": _f("String", required=True)},
        }
        money = {
            "element_type": "VALUE_OBJECT",
            "name": "Money",
            "fqn": "app.Money",
            "fields": {
                "amount": _f("Float", required=True),
                "currency": {
                    "kind": "value_object",
                    "type": "VO",
                    "target": "app.Currency",
                },
            },
        }
        # Order references Money (single + repeated) and Currency directly, so
        # Currency is reached both directly and via Money — exercising the
        # already-emitted dedup guard.
        order = _elem(
            "Order",
            {
                "total": {"kind": "value_object", "type": "VO", "target": "app.Money"},
                "fees": {"kind": "has_many", "type": "VO", "target": "app.Money"},
                "cur": {"kind": "value_object", "type": "VO", "target": "app.Currency"},
            },
        )
        proto = generate_proto_schema(
            order,
            all_elements={
                "app.Money": money,
                "app.Currency": currency,
                "app.Order": order,
            },
        )
        assert "  optional Money total = " in proto  # single value-object ref
        assert "  repeated Money fees = " in proto  # has_many -> repeated
        # Each referenced message is emitted exactly once.
        assert proto.count("message Money {") == 1
        assert proto.count("message Currency {") == 1
