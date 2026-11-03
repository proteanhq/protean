"""Schemas for a ``Dict`` field whose values are a value object.

A ``Dict(value_type=ValueObject(Address))`` field carries the value object's
FQN as ``target`` in the IR, and each schema generator types the map's values
as that value object. An untyped ``Dict()`` keeps the plain map output.
"""

import io
import json
import re

import fastavro
import jsonschema
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.domain import Domain
from protean.fields import Dict, Identifier, Integer, String, ValueObject
from protean.ir import load_schema
from protean.ir.diff import classify_changes, diff_ir
from protean.ir.generators.avro import generate_avro_schema
from protean.ir.generators.protobuf import _map_entry_name, generate_proto_schema
from protean.ir.generators.schema import _build_flat_elements, generate_element_schema
from protean.ir.generators.schema_writer import write_schemas
from protean.utils import fqn


class Address(BaseValueObject):
    street = String(max_length=255, required=True)
    city = String(max_length=100, required=True)


class Contact(BaseAggregate):
    contact_id = Identifier(identifier=True)
    address_book = Dict(value_type=ValueObject(Address))
    tags = Dict()


class Customer(BaseAggregate):
    customer_id = Identifier(identifier=True)
    address_book = Dict(value_type=ValueObject(Address))
    shipping_address = ValueObject(Address)


class Phone(BaseValueObject):
    number = String(max_length=20, required=True)


class Directory(BaseAggregate):
    directory_id = Identifier(identifier=True)
    phones = Dict(value_type=ValueObject(Phone))


class Courier(BaseAggregate):
    # ``depot`` sorts before ``drops``, so the plain field defines the Avro
    # record and the dict's values refer to it by full name.
    courier_id = Identifier(identifier=True)
    depot = ValueObject(Address)
    drops = Dict(value_type=ValueObject(Address))


class Score(BaseAggregate):
    score_id = Identifier(identifier=True)
    counts: dict[str, int] = {}


class LedgerEntry(BaseValueObject):
    note = String(max_length=50, required=True)


class Account(BaseAggregate):
    # protoc names the hidden entry message of the ``ledger`` map
    # ``LedgerEntry``, the same name as the value object.
    account_id = Identifier(identifier=True)
    ledger = Dict(value_type=ValueObject(LedgerEntry))
    primary = ValueObject(LedgerEntry)


@pytest.fixture
def flat(test_domain):
    test_domain.register(Address, part_of=Contact)
    test_domain.register(Contact)
    test_domain.register(Customer)
    # Registered without ``part_of``: Phone joins Directory's cluster only
    # through the ``Dict`` field.
    test_domain.register(Phone)
    test_domain.register(Directory)
    test_domain.register(Courier)
    test_domain.register(Score)
    test_domain.register(LedgerEntry)
    test_domain.register(Account)
    test_domain.init(traverse=False)
    ir = test_domain.to_ir()
    return ir, _build_flat_elements(ir)


def _element(flat_index, cls):
    return flat_index[fqn(cls)]


class TestIRField:
    def test_typed_dict_carries_the_value_object_target(self, flat):
        _, index = flat
        field = _element(index, Contact)["fields"]["address_book"]
        assert field["kind"] == "dict"
        assert field["content_type"] == "Address"
        assert field["target"] == fqn(Address)

    def test_untyped_dict_has_neither_content_type_nor_target(self, flat):
        _, index = flat
        field = _element(index, Contact)["fields"]["tags"]
        assert field["kind"] == "dict"
        assert "content_type" not in field
        assert "target" not in field

    def test_dict_only_value_object_joins_the_cluster(self, flat):
        ir, index = flat
        cluster = ir["clusters"][fqn(Directory)]
        assert list(cluster["value_objects"]) == [fqn(Phone)]
        assert set(index[fqn(Phone)]["fields"]) == {"number"}

    def test_dict_of_a_non_value_object_has_no_target(self, flat):
        _, index = flat
        field = _element(index, Score)["fields"]["counts"]
        assert field["content_type"] == "Integer"
        assert "target" not in field

    def test_ir_validates_against_the_bundled_schema(self, flat):
        ir, _ = flat
        jsonschema.validate(ir, load_schema())

    def test_bundled_schema_declares_dict_content_type_and_target(self):
        properties = load_schema()["$defs"]["field_dict"]["properties"]
        assert properties["content_type"]["type"] == "string"
        assert properties["target"]["type"] == "string"
        assert properties["target"]["minLength"] == 1

    def test_bundled_schema_rejects_an_empty_dict_target(self, flat):
        ir, _ = flat
        ir["clusters"][fqn(Contact)]["aggregate"]["fields"]["address_book"][
            "target"
        ] = ""
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ir, load_schema())


class TestJsonSchema:
    def test_typed_dict_refers_to_the_value_object(self, flat):
        _, index = flat
        schema = generate_element_schema(_element(index, Contact), all_elements=index)
        assert schema["properties"]["address_book"] == {
            "anyOf": [
                {"additionalProperties": {"$ref": "#/$defs/Address"}, "type": "object"},
                {"type": "null"},
            ]
        }
        assert set(schema["$defs"]["Address"]["properties"]) == {"street", "city"}

    def test_untyped_dict_stays_an_object(self, flat):
        _, index = flat
        schema = generate_element_schema(_element(index, Contact), all_elements=index)
        assert schema["properties"]["tags"] == {
            "anyOf": [{"type": "object"}, {"type": "null"}]
        }

    def test_map_values_validate_against_the_value_object(self, flat):
        _, index = flat
        schema = generate_element_schema(_element(index, Contact), all_elements=index)
        jsonschema.validate(
            {
                "contact_id": "c1",
                "address_book": {"home": {"street": "1 A", "city": "X"}},
            },
            schema,
        )
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"contact_id": "c1", "address_book": {"home": "1 A Street"}}, schema
            )
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"contact_id": "c1", "address_book": {"home": {"city": "X"}}},
                schema,
            )

    def test_dict_only_value_object_def_has_its_fields(self, flat):
        _, index = flat
        schema = generate_element_schema(_element(index, Directory), all_elements=index)
        assert schema["$defs"]["Phone"]["properties"] == {
            "number": {"maxLength": 20, "minLength": 1, "type": "string"}
        }

    def test_dict_of_a_non_value_object_stays_an_object(self, flat):
        _, index = flat
        schema = generate_element_schema(_element(index, Score), all_elements=index)
        assert schema["properties"]["counts"]["anyOf"] == [
            {"type": "object"},
            {"type": "null"},
        ]
        assert "$defs" not in schema

    def test_value_object_used_twice_has_one_def(self, flat):
        _, index = flat
        schema = generate_element_schema(_element(index, Customer), all_elements=index)
        assert list(schema["$defs"]) == ["Address"]
        props = schema["properties"]
        assert props["address_book"]["anyOf"][0]["additionalProperties"] == {
            "$ref": "#/$defs/Address"
        }
        assert props["shipping_address"]["anyOf"][0] == {"$ref": "#/$defs/Address"}


class TestAvro:
    def _field_type(self, schema, name):
        field = next(f for f in schema["fields"] if f["name"] == name)
        assert field["type"][0] == "null"
        return field["type"][1]

    def test_typed_dict_is_a_map_of_the_value_object_record(self, flat):
        _, index = flat
        schema = generate_avro_schema(_element(index, Contact), all_elements=index)
        address_book = self._field_type(schema, "address_book")
        assert address_book["type"] == "map"
        record = address_book["values"]
        assert record["type"] == "record"
        assert record["name"] == "Address"
        assert [f["name"] for f in record["fields"]] == ["city", "street"]

    def test_untyped_dict_stays_a_string_map(self, flat):
        _, index = flat
        schema = generate_avro_schema(_element(index, Contact), all_elements=index)
        assert self._field_type(schema, "tags") == {"type": "map", "values": "string"}

    def test_two_addresses_round_trip(self, flat):
        _, index = flat
        schema = generate_avro_schema(_element(index, Contact), all_elements=index)
        parsed = fastavro.parse_schema(schema)
        record = {
            "contact_id": "c1",
            "address_book": {
                "home": {"street": "1 Home Road", "city": "Pune"},
                "work": {"street": "2 Office Lane", "city": "Mumbai"},
            },
            "tags": None,
        }
        buffer = io.BytesIO()
        fastavro.writer(buffer, parsed, [record])
        buffer.seek(0)
        assert list(fastavro.reader(buffer)) == [record]

    def test_value_object_used_twice_is_defined_once(self, flat):
        _, index = flat
        schema = generate_avro_schema(_element(index, Customer), all_elements=index)
        fastavro.parse_schema(schema)  # raises on a duplicate record definition
        address_book = self._field_type(schema, "address_book")
        shipping = self._field_type(schema, "shipping_address")
        # ``address_book`` sorts first, so it defines the record and
        # ``shipping_address`` refers to it by full name.
        assert address_book["values"]["type"] == "record"
        assert shipping == f"{address_book['values']['namespace']}.Address"
        assert json.dumps(schema).count('"type": "record"') == 2  # Customer, Address

    def test_dict_after_the_record_refers_to_it_by_full_name(self, flat):
        _, index = flat
        schema = generate_avro_schema(_element(index, Courier), all_elements=index)
        depot = self._field_type(schema, "depot")
        drops = self._field_type(schema, "drops")
        assert depot["type"] == "record"
        assert drops == {
            "type": "map",
            "values": f"{depot['namespace']}.Address",
        }
        parsed = fastavro.parse_schema(schema)
        record = {
            "courier_id": "c1",
            "depot": {"street": "1 Depot Road", "city": "Pune"},
            "drops": {"a": {"street": "2 Drop Lane", "city": "Mumbai"}},
        }
        buffer = io.BytesIO()
        fastavro.writer(buffer, parsed, [record])
        buffer.seek(0)
        assert list(fastavro.reader(buffer)) == [record]

    def test_dict_only_value_object_record_has_its_fields(self, flat):
        _, index = flat
        schema = generate_avro_schema(_element(index, Directory), all_elements=index)
        record = self._field_type(schema, "phones")["values"]
        assert record["namespace"] == schema["namespace"]
        assert record["fields"] == [{"name": "number", "type": "string"}]

    def test_dict_of_a_non_value_object_stays_a_string_map(self, flat):
        _, index = flat
        schema = generate_avro_schema(_element(index, Score), all_elements=index)
        assert self._field_type(schema, "counts") == {
            "type": "map",
            "values": "string",
        }


class TestProtobuf:
    def test_typed_dict_is_a_map_of_the_value_object_message(self, flat):
        _, index = flat
        text = generate_proto_schema(_element(index, Contact), all_elements=index)
        assert re.search(
            r"^  map<string, Address> address_book = \d+;$", text, re.MULTILINE
        )
        assert text.count("message Address {") == 1

    def test_untyped_dict_stays_a_string_map(self, flat):
        _, index = flat
        text = generate_proto_schema(_element(index, Contact), all_elements=index)
        assert re.search(r"^  map<string, string> tags = \d+;$", text, re.MULTILINE)

    def test_value_object_used_twice_has_one_message(self, flat):
        _, index = flat
        text = generate_proto_schema(_element(index, Customer), all_elements=index)
        assert re.search(
            r"^  map<string, Address> address_book = \d+;$", text, re.MULTILINE
        )
        assert re.search(
            r"^  optional Address shipping_address = \d+;$", text, re.MULTILINE
        )
        assert text.count("message Address {") == 1

    def test_dict_only_value_object_message_has_its_fields(self, flat):
        _, index = flat
        text = generate_proto_schema(_element(index, Directory), all_elements=index)
        assert "message Phone {\n  string number = 1;\n}" in text

    def test_dict_of_a_non_value_object_stays_a_string_map(self, flat):
        _, index = flat
        text = generate_proto_schema(_element(index, Score), all_elements=index)
        assert re.search(r"^  map<string, string> counts = \d+;$", text, re.MULTILINE)

    def test_entry_named_value_object_is_written_by_full_name(self, flat):
        _, index = flat
        text = generate_proto_schema(_element(index, Account), all_elements=index)
        package = re.search(r"^package (\S+);$", text, re.MULTILINE).group(1)
        assert f"  map<string, .{package}.LedgerEntry> ledger = " in text
        assert f"  optional .{package}.LedgerEntry primary = " in text
        assert "message LedgerEntry {" in text

    def test_nested_entry_named_value_object_is_scoped_to_the_message(self):
        entry = {
            "element_type": "VALUE_OBJECT",
            "name": "LedgerEntry",
            "fqn": "app.LedgerEntry",
            "fields": {"note": {"kind": "standard", "type": "String"}},
        }
        book = {
            "element_type": "AGGREGATE",
            "name": "Book",
            "fqn": "app.Book",
            "fields": {"entry": {"kind": "value_object", "target": "app.LedgerEntry"}},
        }
        text = generate_proto_schema(
            book, all_elements={"app.LedgerEntry": entry}, import_path=lambda _: None
        )
        assert "  optional .app.Book.LedgerEntry entry = 1;" in text
        assert "  message LedgerEntry {" in text

    def test_entry_named_self_reference_names_the_main_message(self):
        entry = {
            "element_type": "VALUE_OBJECT",
            "name": "LedgerEntry",
            "fqn": "app.LedgerEntry",
            "fields": {"parent": {"kind": "value_object", "target": "app.LedgerEntry"}},
        }
        text = generate_proto_schema(entry, import_path=lambda _: None)
        assert "  optional .app.LedgerEntry parent = 1;" in text

    def test_written_dict_only_value_object_has_its_own_file(self, flat, tmp_path):
        ir, _ = flat
        written = write_schemas(ir, tmp_path, fmt="protobuf")
        phone = next(p for p in written if p.name == "Phone.v1.proto")
        assert "message Phone {\n  string number = 1;\n}" in phone.read_text()

    def test_written_file_imports_the_value_object_file(self, flat, tmp_path):
        ir, _ = flat
        written = write_schemas(ir, tmp_path, fmt="protobuf")
        contact = next(p for p in written if p.name == "Contact.v1.proto")
        address = next(p for p in written if p.name == "Address.v1.proto")
        text = contact.read_text()
        package = re.search(
            r"^package (\S+);$", address.read_text(), re.MULTILINE
        ).group(1)
        relative = address.relative_to(tmp_path / "schemas").as_posix()
        assert f'import "{relative}";' in text
        assert f"  map<string, .{package}.Address> address_book = " in text
        assert "message Address {" not in text

    def test_dict_reference_counts_towards_an_import_cycle(self, tmp_path):
        # X maps to Y through a typed dict and Y refers back to X. Importing
        # each other's files would be a cycle ``protoc`` rejects, so each file
        # defines the other as a nested message instead.
        x = {
            "element_type": "VALUE_OBJECT",
            "name": "X",
            "fqn": "app.X",
            "fields": {
                "ys": {"kind": "dict", "type": "Dict", "target": "app.Y"},
            },
        }
        y = {
            "element_type": "VALUE_OBJECT",
            "name": "Y",
            "fqn": "app.Y",
            "fields": {"x": {"kind": "value_object", "target": "app.X"}},
        }
        root = {
            "element_type": "AGGREGATE",
            "name": "Root",
            "fqn": "app.Root",
            "fields": {"id": {"kind": "standard", "type": "Identifier"}},
        }
        ir = {
            "clusters": {
                "app.Root": {
                    "aggregate": root,
                    "value_objects": {"app.X": x, "app.Y": y},
                }
            },
            "projections": {},
        }
        write_schemas(ir, tmp_path, fmt="protobuf")
        schemas = tmp_path / "schemas" / "Root" / "value_objects"
        x_text = (schemas / "X.v1.proto").read_text()
        y_text = (schemas / "Y.v1.proto").read_text()
        assert "import " not in x_text
        assert "import " not in y_text
        assert "  map<string, Y> ys = 1;" in x_text
        assert "  message Y {" in x_text
        assert "  message X {" in y_text

    def test_nested_value_object_named_like_a_map_entry_is_renamed(self, tmp_path):
        # Book maps to LedgerEntry through ``ledger`` and LedgerEntry refers
        # back to Book, so Book's file nests LedgerEntry. protoc also defines
        # ``Book.LedgerEntry`` for the ``ledger`` map, so the nested message
        # takes another name.
        entry = {
            "element_type": "VALUE_OBJECT",
            "name": "LedgerEntry",
            "fqn": "app.LedgerEntry",
            "fields": {"book": {"kind": "value_object", "target": "app.Book"}},
        }
        book = {
            "element_type": "VALUE_OBJECT",
            "name": "Book",
            "fqn": "app.Book",
            "fields": {
                "ledger": {"kind": "dict", "type": "Dict", "target": "app.LedgerEntry"},
                "latest": {"kind": "value_object", "target": "app.LedgerEntry"},
            },
        }
        root = {
            "element_type": "AGGREGATE",
            "name": "Root",
            "fqn": "app.Root",
            "fields": {"id": {"kind": "standard", "type": "Identifier"}},
        }
        ir = {
            "clusters": {
                "app.Root": {
                    "aggregate": root,
                    "value_objects": {"app.Book": book, "app.LedgerEntry": entry},
                }
            },
            "projections": {},
        }
        write_schemas(ir, tmp_path, fmt="protobuf")
        schemas = tmp_path / "schemas" / "Root" / "value_objects"
        book_text = (schemas / "Book.v1.proto").read_text()
        assert "import " not in book_text
        assert "  map<string, LedgerEntry_> ledger = 2;" in book_text
        assert "  optional LedgerEntry_ latest = 1;" in book_text
        assert "  message LedgerEntry_ {" in book_text
        assert "message LedgerEntry {" not in book_text

    def test_renamed_nested_message_skips_a_name_already_in_use(self, tmp_path):
        # Book nests both LedgerEntry and a value object already named
        # LedgerEntry_, so the renamed LedgerEntry takes yet another name.
        entry = {
            "element_type": "VALUE_OBJECT",
            "name": "LedgerEntry",
            "fqn": "app.LedgerEntry",
            "fields": {"book": {"kind": "value_object", "target": "app.Book"}},
        }
        other = {
            "element_type": "VALUE_OBJECT",
            "name": "LedgerEntry_",
            "fqn": "app.LedgerEntry_",
            "fields": {"book": {"kind": "value_object", "target": "app.Book"}},
        }
        book = {
            "element_type": "VALUE_OBJECT",
            "name": "Book",
            "fqn": "app.Book",
            "fields": {
                "ledger": {"kind": "dict", "type": "Dict", "target": "app.LedgerEntry"},
                "other": {"kind": "value_object", "target": "app.LedgerEntry_"},
            },
        }
        root = {
            "element_type": "AGGREGATE",
            "name": "Root",
            "fqn": "app.Root",
            "fields": {"id": {"kind": "standard", "type": "Identifier"}},
        }
        ir = {
            "clusters": {
                "app.Root": {
                    "aggregate": root,
                    "value_objects": {
                        "app.Book": book,
                        "app.LedgerEntry": entry,
                        "app.LedgerEntry_": other,
                    },
                }
            },
            "projections": {},
        }
        write_schemas(ir, tmp_path, fmt="protobuf")
        schemas = tmp_path / "schemas" / "Root" / "value_objects"
        book_text = (schemas / "Book.v1.proto").read_text()
        assert "  map<string, LedgerEntry__> ledger = 1;" in book_text
        assert "  optional LedgerEntry_ other = 2;" in book_text
        assert book_text.count("  message LedgerEntry_ {") == 1
        assert book_text.count("  message LedgerEntry__ {") == 1

    def test_map_entry_name_follows_protoc(self):
        assert _map_entry_name("ledger") == "LedgerEntry"
        assert _map_entry_name("address_book") == "AddressBookEntry"
        assert _map_entry_name("_a__b1c") == "AB1cEntry"


class TestCompatibility:
    @staticmethod
    def _build(phone_fields):
        domain = Domain(name="Book")
        phone = domain.value_object(
            type("Phone", (), {"__module__": "book", **phone_fields})
        )
        domain.aggregate(
            type(
                "Directory",
                (),
                {"__module__": "book", "phones": Dict(value_type=ValueObject(phone))},
            )
        )
        domain.init(traverse=False)
        return domain.to_ir()

    @pytest.mark.no_test_domain
    def test_required_field_on_a_dict_only_value_object_breaks(self):
        left = self._build({"number": String()})
        right = self._build({"number": String(), "zip": Integer(required=True)})
        report = classify_changes(diff_ir(left, right), left, right)
        assert [
            (c.element_fqn, c.change_type, c.field_name)
            for c in report.breaking_changes
        ] == [("book.Phone", "required_field_added", "zip")]
