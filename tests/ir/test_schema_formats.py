"""Tests for IR -> Avro and Protobuf schema emission.

Covers field-type mapping, optional handling (Avro unions / proto3 `optional`),
logical / well-known types, deterministic Protobuf field numbers, per-version
file emission, and an fastavro round-trip parse of the generated Avro.
"""

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject
from protean.ir.generators.avro import generate_avro_schema
from protean.ir.generators.protobuf import generate_proto_schema
from protean.ir.generators.schema_writer import (
    _relative_schema_path,
    write_all_schemas,
    write_schemas,
)


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

    def test_without_import_path_referenced_messages_are_inlined(self):
        # With no path lookup the file stays self-contained: Money and Currency
        # are emitted as sibling messages and named by their short names.
        currency = {
            "element_type": "VALUE_OBJECT",
            "name": "Currency",
            "fqn": "app.Currency",
            "fields": {"code": _f("String", required=True), "at": _f("DateTime")},
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
        # Currency is reached both directly and via Money, exercising the
        # already-emitted guard.
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
        assert proto == (
            'syntax = "proto3";\n'
            "package app;\n"
            'import "google/protobuf/timestamp.proto";\n'
            "\n"
            "message Order {\n"
            "  optional Currency cur = 1;\n"
            "  repeated Money fees = 2;\n"
            "  optional Money total = 3;\n"
            "}\n"
            "\n"
            "message Currency {\n"
            "  optional google.protobuf.Timestamp at = 1;\n"
            "  string code = 2;\n"
            "}\n"
            "\n"
            "message Money {\n"
            "  double amount = 1;\n"
            "  optional Currency currency = 2;\n"
            "}\n"
        )


# ---------------------------------------------------------------------------
# Protobuf trees: files import each other and define each message once
# ---------------------------------------------------------------------------

_PROTO_SCALARS = {
    "string",
    "bytes",
    "bool",
    "int32",
    "int64",
    "uint32",
    "uint64",
    "sint32",
    "sint64",
    "fixed32",
    "fixed64",
    "sfixed32",
    "sfixed64",
    "float",
    "double",
}
_TIMESTAMP_IMPORT = "google/protobuf/timestamp.proto"
_PACKAGE_RE = re.compile(r"^package ([\w.]+);$", re.MULTILINE)
_IMPORT_RE = re.compile(r'^import "([^"]+)";$', re.MULTILINE)
_MESSAGE_RE = re.compile(r"^message (\w+) \{$", re.MULTILINE)
_FIELD_RE = re.compile(
    r"^  (?:optional |repeated )?(map<string, string>|[.\w]+) \w+ = \d+;$", re.MULTILINE
)


def _parse_proto(text: str) -> dict[str, Any]:
    package = _PACKAGE_RE.search(text)
    assert package is not None
    return {
        "package": package.group(1),
        "imports": _IMPORT_RE.findall(text),
        "messages": _MESSAGE_RE.findall(text),
        "types": _FIELD_RE.findall(text),
    }


def _assert_valid_proto_tree(schemas_dir: Path) -> dict[str, dict[str, Any]]:
    """Check a written ``.proto`` tree the way ``protoc`` would, without it.

    Every ``<package>.<message>`` is defined once across the tree, every import
    names a file in the tree, and every non-scalar field type resolves to a
    message the file defines or imports. Returns the parsed files by path.
    """
    files = {
        p.relative_to(schemas_dir).as_posix(): _parse_proto(p.read_text())
        for p in sorted(schemas_dir.rglob("*.proto"))
    }
    assert files, "the tree holds no .proto files"

    defined_in: dict[str, list[str]] = {}
    for path, parsed in files.items():
        for message in parsed["messages"]:
            defined_in.setdefault(f"{parsed['package']}.{message}", []).append(path)
    duplicates = {name: paths for name, paths in defined_in.items() if len(paths) > 1}
    assert duplicates == {}

    for path, parsed in files.items():
        visible = {f"{parsed['package']}.{m}" for m in parsed["messages"]}
        for imported in parsed["imports"]:
            if imported == _TIMESTAMP_IMPORT:
                continue
            assert imported in files, f"{path} imports missing {imported}"
            target = files[imported]
            visible |= {f"{target['package']}.{m}" for m in target["messages"]}

        for proto_type in parsed["types"]:
            if proto_type in _PROTO_SCALARS or proto_type == "map<string, string>":
                continue
            if proto_type == "google.protobuf.Timestamp":
                assert _TIMESTAMP_IMPORT in parsed["imports"]
                continue
            if proto_type.startswith("."):
                full_name = proto_type[1:]
            else:
                # A bare name resolves inside the file's own package.
                full_name = f"{parsed['package']}.{proto_type}"
            assert full_name in visible, f"{path}: {proto_type} does not resolve"
    return files


def _vo_field(target: str, kind: str = "value_object") -> dict[str, Any]:
    return {"kind": kind, "type": "VO", "target": target}


# Module-level, so the fqn (and with it the proto package) is a plain dotted
# module path; a class defined in a function carries "<locals>" in its fqn.
class Dimensions(BaseValueObject):
    weight = Float()


class Package(BaseEntity):
    dimensions = ValueObject(Dimensions)


class Order(BaseAggregate):
    name = String()
    packages = HasMany(Package)


class TestProtobufSchemaTree:
    def _repro_ir(self, test_domain):
        test_domain.register(Order)
        test_domain.register(Package, part_of=Order)
        test_domain.register(Dimensions, part_of=Order)
        test_domain.init(traverse=False)
        return test_domain.to_ir()

    def test_repro_tree_defines_each_message_once_and_imports_it(
        self, test_domain, tmp_path
    ):
        write_schemas(self._repro_ir(test_domain), tmp_path, fmt="protobuf")
        files = _assert_valid_proto_tree(tmp_path / "schemas")

        dims_path = "Order/value_objects/Dimensions.v1.proto"
        package_path = "Order/entities/Package.v1.proto"
        order_path = "Order/aggregates/Order.v1.proto"
        assert [p for p, f in files.items() if "Dimensions" in f["messages"]] == [
            dims_path
        ]
        assert [p for p, f in files.items() if "Package" in f["messages"]] == [
            package_path
        ]

        order_text = (tmp_path / "schemas" / order_path).read_text()
        package_pkg = files[package_path]["package"]
        assert f'import "{package_path}";' in order_text
        assert f"  repeated .{package_pkg}.Package packages = " in order_text

        package_text = (tmp_path / "schemas" / package_path).read_text()
        dims_pkg = files[dims_path]["package"]
        assert f'import "{dims_path}";' in package_text
        assert f"  optional .{dims_pkg}.Dimensions dimensions = " in package_text

    def test_rewriting_the_tree_is_byte_identical(self, test_domain, tmp_path):
        ir = self._repro_ir(test_domain)
        first = {
            p.relative_to(tmp_path / "a"): p.read_bytes()
            for p in write_schemas(ir, tmp_path / "a", fmt="protobuf")
        }
        second = {
            p.relative_to(tmp_path / "b"): p.read_bytes()
            for p in write_schemas(ir, tmp_path / "b", fmt="protobuf")
        }
        assert first
        assert first == second

    def test_write_all_schemas_writes_the_importing_tree(self, test_domain, tmp_path):
        write_all_schemas(self._repro_ir(test_domain), tmp_path)
        _assert_valid_proto_tree(tmp_path / "schemas")
        order = (tmp_path / "schemas/Order/aggregates/Order.v1.proto").read_text()
        assert 'import "Order/entities/Package.v1.proto";' in order
        assert "message Package {" not in order

    @staticmethod
    def _cross_module_ir() -> dict[str, Any]:
        money = {
            "element_type": "VALUE_OBJECT",
            "name": "Money",
            "fqn": "shared.kernel.Money",
            "fields": {
                "amount": _f("Float", required=True),
                "at": _f("DateTime"),
            },
        }
        order = {
            "element_type": "AGGREGATE",
            "name": "Order",
            "fqn": "sales.ordering.Order",
            "fields": {
                "id": _f("Identifier", identifier=True),
                "total": _vo_field("shared.kernel.Money"),
                "fee": _vo_field("shared.kernel.Money"),
                "placed_at": _f("DateTime"),
            },
        }
        return {
            "clusters": {
                "shared.kernel.Wallet": {
                    "aggregate": {
                        "element_type": "AGGREGATE",
                        "name": "Wallet",
                        "fqn": "shared.kernel.Wallet",
                        "fields": {"id": _f("Identifier", identifier=True)},
                    },
                    "value_objects": {"shared.kernel.Money": money},
                },
                "sales.ordering.Order": {"aggregate": order},
            },
            "projections": {},
        }

    def test_cross_module_value_object_keeps_its_own_full_name(self, tmp_path):
        write_schemas(self._cross_module_ir(), tmp_path, fmt="protobuf")
        _assert_valid_proto_tree(tmp_path / "schemas")

        order = (tmp_path / "schemas/Order/aggregates/Order.v1.proto").read_text()
        money_import = 'import "Wallet/value_objects/Money.v1.proto";'
        assert order.count(money_import) == 1
        assert "  optional .shared.kernel.Money fee = " in order
        assert "  optional .shared.kernel.Money total = " in order
        assert "message Money {" not in order
        # Imports are one sorted list, the timestamp import included.
        imports = _IMPORT_RE.findall(order)
        assert imports == sorted(imports)
        assert imports == [
            "Wallet/value_objects/Money.v1.proto",
            _TIMESTAMP_IMPORT,
        ]

    def test_repeating_package_parts_use_root_relative_names(self, tmp_path):
        # In package f.f.f, protoc would read a bare "f.f.f.V" as "f.f.f.f.f.V",
        # so a cross-file type must carry the leading dot.
        vo = {
            "element_type": "VALUE_OBJECT",
            "name": "V",
            "fqn": "f.f.f.V",
            "fields": {"x": _f("String")},
        }
        agg = {
            "element_type": "AGGREGATE",
            "name": "A",
            "fqn": "f.f.f.A",
            "fields": {"v": _vo_field("f.f.f.V")},
        }
        ir = {
            "clusters": {
                "f.f.f.A": {"aggregate": agg, "value_objects": {"f.f.f.V": vo}}
            },
            "projections": {},
        }
        write_schemas(ir, tmp_path, fmt="protobuf")
        _assert_valid_proto_tree(tmp_path / "schemas")
        text = (tmp_path / "schemas/A/aggregates/A.v1.proto").read_text()
        assert "  optional .f.f.f.V v = 1;" in text

    def test_reference_field_is_string_and_adds_no_import(self, tmp_path):
        agg = {
            "element_type": "AGGREGATE",
            "name": "Order",
            "fqn": "app.Order",
            "fields": {
                "id": _f("Identifier", identifier=True),
                "items": _vo_field("app.Item", kind="has_many"),
            },
        }
        item = {
            "element_type": "ENTITY",
            "name": "Item",
            "fqn": "app.Item",
            "fields": {"order": {"kind": "reference", "type": "Ref", "to": "Order"}},
        }
        ir = {
            "clusters": {
                "app.Order": {"aggregate": agg, "entities": {"app.Item": item}}
            },
            "projections": {},
        }
        write_schemas(ir, tmp_path, fmt="protobuf")
        _assert_valid_proto_tree(tmp_path / "schemas")
        text = (tmp_path / "schemas/Order/entities/Item.v1.proto").read_text()
        assert "  optional string order = 1;" in text
        assert "import " not in text

    def test_self_reference_imports_nothing(self, tmp_path):
        node = {
            "element_type": "VALUE_OBJECT",
            "name": "Node",
            "fqn": "app.Node",
            "fields": {"child": _vo_field("app.Node")},
        }
        agg = {
            "element_type": "AGGREGATE",
            "name": "Tree",
            "fqn": "app.Tree",
            "fields": {"id": _f("Identifier", identifier=True)},
        }
        ir = {
            "clusters": {
                "app.Tree": {"aggregate": agg, "value_objects": {"app.Node": node}}
            },
            "projections": {},
        }
        write_schemas(ir, tmp_path, fmt="protobuf")
        _assert_valid_proto_tree(tmp_path / "schemas")
        text = (tmp_path / "schemas/Tree/value_objects/Node.v1.proto").read_text()
        assert "  optional Node child = 1;" in text
        assert "import " not in text

    def test_projection_imports_value_object_from_its_cluster(self, tmp_path):
        money = {
            "element_type": "VALUE_OBJECT",
            "name": "Money",
            "fqn": "app.Money",
            "fields": {"amount": _f("Float")},
        }
        agg = {
            "element_type": "AGGREGATE",
            "name": "Order",
            "fqn": "app.Order",
            "fields": {"id": _f("Identifier", identifier=True)},
        }
        dashboard = {
            "element_type": "PROJECTION",
            "name": "Dashboard",
            "fqn": "app.Dashboard",
            "fields": {"total": _vo_field("app.Money")},
        }
        ir = {
            "clusters": {
                "app.Order": {"aggregate": agg, "value_objects": {"app.Money": money}}
            },
            "projections": {"app.Dashboard": {"projection": dashboard}},
        }
        write_schemas(ir, tmp_path, fmt="protobuf")
        _assert_valid_proto_tree(tmp_path / "schemas")
        text = (tmp_path / "schemas/projections/Dashboard.v1.proto").read_text()
        assert 'import "Order/value_objects/Money.v1.proto";' in text
        assert "  optional .app.Money total = 1;" in text

    def test_target_without_a_file_is_inlined_without_an_import(self):
        money = {
            "element_type": "VALUE_OBJECT",
            "name": "Money",
            "fqn": "app.Money",
            "fields": {"amount": _f("Float")},
        }
        currency = {
            "element_type": "VALUE_OBJECT",
            "name": "Currency",
            "fqn": "app.Currency",
            "fields": {"code": _f("String")},
        }
        order = _elem(
            "Order",
            {"total": _vo_field("app.Money"), "cur": _vo_field("app.Currency")},
        )
        paths = {"app.Currency": "Order/value_objects/Currency.v1.proto"}
        proto = generate_proto_schema(
            order,
            all_elements={"app.Money": money, "app.Currency": currency},
            import_path=paths.get,
        )
        # Currency has a file, so it is imported; Money has none, so it is
        # emitted here as a sibling message.
        assert 'import "Order/value_objects/Currency.v1.proto";' in proto
        assert "  optional .app.Currency cur = 1;" in proto
        assert "message Currency {" not in proto
        assert "  optional Money total = 2;" in proto
        assert "message Money {" in proto
        assert _IMPORT_RE.findall(proto) == ["Order/value_objects/Currency.v1.proto"]


class TestRelativeSchemaPath:
    def test_cluster_member_and_projection_paths(self):
        ir = {
            "clusters": {
                "app.Order": {
                    "aggregate": {"fqn": "app.Order"},
                    "value_objects": {"app.Money": {}},
                }
            }
        }
        money = {"element_type": "VALUE_OBJECT", "name": "Money", "__version__": 3}
        dash = {"element_type": "PROJECTION", "name": "Dash"}
        assert _relative_schema_path("app.Money", money, ir, "proto") == (
            PurePosixPath("Order/value_objects/Money.v3.proto")
        )
        assert _relative_schema_path("app.Dash", dash, ir, "json") == (
            PurePosixPath("projections/Dash.v1.json")
        )

    def test_element_outside_any_cluster_uses_its_short_name(self):
        loose = {"element_type": "EVENT", "name": "Loose"}
        assert _relative_schema_path("app.Loose", loose, {}, "avsc") == (
            PurePosixPath("Loose/events/Loose.v1.avsc")
        )
