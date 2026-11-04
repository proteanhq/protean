"""IR and schemas for a ``ValueObject`` field on a command or event.

A command or event turns its ``ValueObject`` fields into plain resolved fields
typed by the value object class. The IR records each one as a ``value_object``
field with the value object's FQN as ``target``, the kind and target an
aggregate's ``ValueObject`` field gets, and a value object that only messages
hold joins the message's aggregate cluster.
"""

import re
from typing import Annotated

import fastavro
import jsonschema
import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.query import BaseQuery
from protean.core.value_object import BaseValueObject
from protean.domain import Domain
from protean.fields import Custom, Identifier, List, String, ValueObject
from protean.ir import load_schema
from protean.ir.diff import classify_changes, diff_ir
from protean.ir.generators.avro import generate_avro_schema
from protean.ir.generators.protobuf import generate_proto_schema
from protean.ir.generators.schema import _build_flat_elements, generate_element_schema
from protean.ir.generators.schema_writer import write_schemas
from protean.utils import fqn


class Addr(BaseValueObject):
    city = String(max_length=50, required=True)


class Shared(BaseValueObject):
    zone = String(max_length=10)


class Pinned(BaseValueObject):
    code = String(max_length=10)


class Acct(BaseAggregate):
    acct_id = Identifier(identifier=True)
    name = String()


class Other(BaseAggregate):
    other_id = Identifier(identifier=True)
    shared = ValueObject(Shared)


class Moved(BaseEvent):
    acct_id = Identifier()
    addr = ValueObject(Addr)
    home = ValueObject(Addr, required=True)
    shared = ValueObject(Shared)
    pinned = ValueObject(Pinned)
    note = String()
    addrs = List(content_type=ValueObject(Addr))


class Relocated(BaseEvent):
    acct_id = Identifier()
    addr: ValueObject(Addr)
    home: Addr


class Move(BaseCommand):
    acct_id = Identifier()
    addr = ValueObject(Addr)
    home = ValueObject(Addr, required=True)


class Relocate(BaseCommand):
    acct_id = Identifier()
    addr: ValueObject(Addr)
    home: Addr


class AcctView(BaseProjection):
    acct_id = Identifier(identifier=True)


class FindByAddr(BaseQuery):
    addr = ValueObject(Addr)


@pytest.fixture
def flat(test_domain):
    # Addr is registered without ``part_of`` and no aggregate field holds it,
    # so only the messages place it in a cluster.
    test_domain.register(Addr)
    test_domain.register(Shared)
    test_domain.register(Pinned, part_of=Other)
    test_domain.register(Acct)
    test_domain.register(Other)
    test_domain.register(Moved, part_of=Acct)
    test_domain.register(Relocated, part_of=Acct)
    test_domain.register(Move, part_of=Acct)
    test_domain.register(Relocate, part_of=Acct)
    test_domain.register(AcctView)
    test_domain.register(FindByAddr, part_of=AcctView)
    test_domain.init(traverse=False)
    ir = test_domain.to_ir()
    return ir, _build_flat_elements(ir)


def _fields(index, cls):
    return index[fqn(cls)]["fields"]


class TestIRField:
    @pytest.mark.parametrize("message", [Moved, Move], ids=["event", "command"])
    def test_value_object_field_is_a_value_object_entry(self, flat, message):
        _, index = flat
        assert _fields(index, message)["addr"] == {
            "kind": "value_object",
            "target": fqn(Addr),
        }

    @pytest.mark.parametrize("message", [Moved, Move], ids=["event", "command"])
    def test_required_value_object_field_is_required(self, flat, message):
        _, index = flat
        assert _fields(index, message)["home"] == {
            "kind": "value_object",
            "required": True,
            "target": fqn(Addr),
        }

    @pytest.mark.parametrize("message", [Relocated, Relocate], ids=["event", "command"])
    def test_annotation_form_is_a_value_object_entry(self, flat, message):
        _, index = flat
        assert _fields(index, message)["addr"] == {
            "kind": "value_object",
            "target": fqn(Addr),
        }

    @pytest.mark.parametrize("message", [Relocated, Relocate], ids=["event", "command"])
    def test_bare_annotation_is_a_value_object_entry(self, flat, message):
        _, index = flat
        assert _fields(index, message)["home"] == {
            "kind": "value_object",
            "required": True,
            "target": fqn(Addr),
        }

    def test_plain_string_field_stays_standard(self, flat):
        _, index = flat
        assert _fields(index, Moved)["note"] == {
            "kind": "standard",
            "max_length": 255,
            "type": "String",
        }

    def test_list_of_value_objects_keeps_its_list_entry(self, flat):
        _, index = flat
        assert _fields(index, Moved)["addrs"] == {
            "content_type": "Addr",
            "default": "<callable>",
            "kind": "list",
            "type": "List",
        }

    def test_query_value_object_field_keeps_its_entry(self, flat):
        ir, _ = flat
        queries = ir["projections"][fqn(AcctView)]["queries"]
        assert queries[fqn(FindByAddr)]["fields"]["addr"] == {
            "kind": "standard",
            "type": "String",
        }

    def test_ir_validates_against_the_bundled_schema(self, flat):
        ir, _ = flat
        jsonschema.validate(ir, load_schema())


class Either(BaseEvent):
    acct_id = Identifier()
    either: Addr | str


class WithMetadata(BaseEvent):
    acct_id = Identifier()
    either: Addr | str
    described: Annotated[Addr, Field(description="Where to")]
    marked = Custom(Addr, deprecated={"since": "0.18"})
    preset: Addr | None = Addr(city="Pune")


class TestIRFieldMetadata:
    @pytest.fixture
    def fields(self, test_domain):
        test_domain.register(Addr)
        test_domain.register(Acct)
        test_domain.register(WithMetadata, part_of=Acct)
        test_domain.init(traverse=False)
        ir = test_domain.to_ir()
        jsonschema.validate(ir, load_schema())
        return _fields(_build_flat_elements(ir), WithMetadata)

    def test_union_with_another_type_keeps_its_standard_entry(self, fields):
        assert fields["either"]["kind"] == "standard"

    def test_union_with_another_type_does_not_place_the_value_object(self, test_domain):
        test_domain.register(Addr)
        test_domain.register(Acct)
        test_domain.register(Either, part_of=Acct)
        test_domain.init(traverse=False)
        assert test_domain.to_ir()["clusters"][fqn(Acct)]["value_objects"] == {}

    def test_description_is_kept(self, fields):
        assert fields["described"] == {
            "description": "Where to",
            "kind": "value_object",
            "required": True,
            "target": fqn(Addr),
        }

    def test_deprecation_is_kept(self, fields):
        assert fields["marked"] == {
            "deprecated": {"since": "0.18"},
            "kind": "value_object",
            "target": fqn(Addr),
        }

    def test_default_is_kept(self, fields):
        assert fields["preset"] == {
            "default": {"city": "Pune"},
            "kind": "value_object",
            "target": fqn(Addr),
        }


class TestCluster:
    def test_message_only_value_object_joins_the_message_cluster(self, flat):
        ir, index = flat
        assert list(ir["clusters"][fqn(Acct)]["value_objects"]) == [fqn(Addr)]
        assert set(index[fqn(Addr)]["fields"]) == {"city"}

    def test_value_object_an_aggregate_holds_stays_in_that_cluster(self, flat):
        ir, _ = flat
        assert fqn(Shared) in ir["clusters"][fqn(Other)]["value_objects"]
        assert fqn(Shared) not in ir["clusters"][fqn(Acct)]["value_objects"]

    def test_part_of_value_object_stays_in_its_declared_cluster(self, flat):
        ir, _ = flat
        assert fqn(Pinned) in ir["clusters"][fqn(Other)]["value_objects"]
        assert fqn(Pinned) not in ir["clusters"][fqn(Acct)]["value_objects"]


class Tagged(BaseValueObject):
    tags = List(content_type=String)


class Left(BaseAggregate):
    left_id = Identifier(identifier=True)


class Right(BaseAggregate):
    right_id = Identifier(identifier=True)


class LeftMoved(BaseEvent):
    left_id = Identifier()
    tagged = ValueObject(Tagged)


class TagRight(BaseCommand):
    right_id = Identifier()
    tagged = ValueObject(Tagged)


class Tagging(BaseEvent):
    tagged = ValueObject(Tagged)


class LeftTagged(Tagging):
    left_id = Identifier()


class TestClusterOrder:
    def test_command_is_scanned_before_an_event(self, test_domain):
        # The event registers first, but commands are scanned before events.
        test_domain.register(Tagged)
        test_domain.register(Left)
        test_domain.register(Right)
        test_domain.register(LeftMoved, part_of=Left)
        test_domain.register(TagRight, part_of=Right)
        test_domain.init(traverse=False)
        clusters = test_domain.to_ir()["clusters"]
        assert list(clusters[fqn(Right)]["value_objects"]) == [fqn(Tagged)]
        assert list(clusters[fqn(Left)]["value_objects"]) == []

    def test_abstract_base_event_does_not_hide_its_subclass_cluster(self, test_domain):
        # The abstract base registers first and has no aggregate. The value
        # object must still join the cluster of the concrete subclass.
        test_domain.register(Tagged)
        test_domain.register(Left)
        test_domain.register(Tagging, abstract=True)
        test_domain.register(LeftTagged, part_of=Left)
        test_domain.init(traverse=False)
        clusters = test_domain.to_ir()["clusters"]
        assert list(clusters[fqn(Left)]["value_objects"]) == [fqn(Tagged)]


class TestDiagnostics:
    def test_mutable_field_on_a_message_only_value_object_is_reported(
        self, test_domain
    ):
        test_domain.register(Tagged)
        test_domain.register(Left)
        test_domain.register(LeftMoved, part_of=Left)
        test_domain.init(traverse=False)
        findings = [
            (d["element"], d["field"])
            for d in test_domain.to_ir()["diagnostics"]
            if d["code"] == "VALUE_OBJECT_MUTABLE_FIELD"
        ]
        assert findings == [(fqn(Tagged), "tags")]


class TestJsonSchema:
    def test_value_object_field_refers_to_the_value_object(self, flat):
        _, index = flat
        schema = generate_element_schema(index[fqn(Moved)], all_elements=index)
        assert schema["properties"]["addr"]["anyOf"][0] == {"$ref": "#/$defs/Addr"}
        assert schema["properties"]["home"] == {"$ref": "#/$defs/Addr"}
        assert set(schema["$defs"]["Addr"]["properties"]) == {"city"}


class TestAvro:
    def _field_type(self, schema, name):
        return next(f for f in schema["fields"] if f["name"] == name)["type"]

    def test_value_object_field_is_the_value_object_record(self, flat):
        _, index = flat
        schema = generate_avro_schema(index[fqn(Moved)], all_elements=index)
        null, record = self._field_type(schema, "addr")
        assert null == "null"
        assert record["type"] == "record"
        assert record["name"] == "Addr"
        assert record["fields"] == [{"name": "city", "type": "string"}]
        # ``home`` sorts after ``addr``, so it refers to the record by full name.
        assert self._field_type(schema, "home") == f"{record['namespace']}.Addr"
        fastavro.parse_schema(schema)


class TestProtobuf:
    def test_value_object_field_is_the_value_object_message(self, flat):
        _, index = flat
        text = generate_proto_schema(index[fqn(Moved)], all_elements=index)
        assert re.search(r"^  optional Addr addr = \d+;$", text, re.MULTILINE)
        assert re.search(r"^  Addr home = \d+;$", text, re.MULTILINE)
        assert text.count("message Addr {") == 1

    def test_written_event_imports_the_value_object_file(self, flat, tmp_path):
        ir, _ = flat
        written = write_schemas(ir, tmp_path, fmt="protobuf")
        moved = next(p for p in written if p.name == "Moved.v1.proto")
        addr = next(p for p in written if p.name == "Addr.v1.proto")
        text = moved.read_text()
        package = re.search(r"^package (\S+);$", addr.read_text(), re.MULTILINE)
        relative = addr.relative_to(tmp_path / "schemas").as_posix()
        assert f'import "{relative}";' in text
        assert f"  optional .{package.group(1)}.Addr addr = " in text
        assert "message Addr {" not in text


class TestCompatibility:
    @staticmethod
    def _build(addr_fields, *, held_by_aggregate):
        domain = Domain(name="Book")
        addr = domain.value_object(
            type("Addr", (), {"__module__": "book", **addr_fields})
        )
        acct_fields = {"__module__": "book", "acct_id": Identifier(identifier=True)}
        if held_by_aggregate:
            acct_fields["addr"] = ValueObject(addr)
        acct = domain.aggregate(type("Acct", (), acct_fields))
        domain.event(
            type(
                "Moved",
                (),
                {
                    "__module__": "book",
                    "acct_id": Identifier(),
                    "addr": ValueObject(addr),
                },
            ),
            part_of=acct,
        )
        domain.init(traverse=False)
        return domain.to_ir()

    def _value_object_changes(self, held_by_aggregate):
        left = self._build({"city": String()}, held_by_aggregate=held_by_aggregate)
        right = self._build(
            {"town": String(renamed_from="city")},
            held_by_aggregate=held_by_aggregate,
        )
        report = classify_changes(diff_ir(left, right), left, right)
        return sorted(
            (c.element_fqn, c.change_type, c.field_name, c.severity)
            for c in report.breaking_changes + report.safe_changes
            if c.element_fqn == "book.Addr"
        )

    @pytest.mark.no_test_domain
    def test_rename_on_a_message_only_value_object_is_reported(self):
        changes = self._value_object_changes(held_by_aggregate=False)
        assert changes == [("book.Addr", "field_renamed", None, "safe")]
        assert changes == self._value_object_changes(held_by_aggregate=True)
