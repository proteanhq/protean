"""Tests that the IR schema is valid JSON Schema 2020-12."""

import json

import pytest

from protean.ir import SCHEMA_PATH, load_schema


@pytest.mark.no_test_domain
class TestSchemaFile:
    """Verify the schema file is loadable and well-formed."""

    def test_schema_file_exists(self):
        assert SCHEMA_PATH.exists(), f"Schema file missing at {SCHEMA_PATH}"

    def test_schema_is_valid_json(self):
        data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_load_schema_returns_dict(self):
        schema = load_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "required" in schema

    def test_schema_meta_keys(self):
        schema = load_schema()
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"] == "https://protean.dev/ir/v0.1.0/schema.json"
        assert schema["title"] == "Protean IR v0.1.0"
        assert "$defs" in schema


@pytest.mark.no_test_domain
class TestSchemaCompleteness:
    """Verify key definitions exist in the schema."""

    def test_all_element_definitions_present(self):
        defs = load_schema()["$defs"]
        expected = [
            "aggregate",
            "application_service",
            "command",
            "command_handler",
            "database_model",
            "domain_service",
            "entity",
            "event",
            "event_handler",
            "process_manager",
            "projection",
            "projector",
            "query",
            "query_handler",
            "repository",
            "subscriber",
            "value_object",
        ]
        for defn in expected:
            assert defn in defs, f"Missing $defs/{defn}"

    def test_field_kind_definitions_present(self):
        defs = load_schema()["$defs"]
        field_kinds = [
            "field_auto",
            "field_dict",
            "field_has_many",
            "field_has_one",
            "field_identifier",
            "field_list",
            "field_reference",
            "field_standard",
            "field_status",
            "field_text",
            "field_value_object",
            "field_value_object_list",
        ]
        for kind in field_kinds:
            assert kind in defs, f"Missing $defs/{kind}"

    def test_elements_index_requires_all_types(self):
        elements_index = load_schema()["$defs"]["elements_index"]
        required = elements_index["required"]
        expected_types = [
            "AGGREGATE",
            "APPLICATION_SERVICE",
            "COMMAND",
            "COMMAND_HANDLER",
            "DATABASE_MODEL",
            "DOMAIN_SERVICE",
            "ENTITY",
            "EVENT",
            "EVENT_HANDLER",
            "PROCESS_MANAGER",
            "PROJECTION",
            "PROJECTOR",
            "QUERY",
            "QUERY_HANDLER",
            "REPOSITORY",
            "SUBSCRIBER",
            "VALUE_OBJECT",
        ]
        for etype in expected_types:
            assert etype in required, f"Missing element type {etype} in elements_index"

    def test_top_level_required_properties(self):
        schema = load_schema()
        required = schema["required"]
        expected = [
            "$schema",
            "ir_version",
            "generated_at",
            "checksum",
            "domain",
            "clusters",
            "projections",
            "flows",
            "elements",
            "diagnostics",
        ]
        for prop in expected:
            assert prop in required, f"Missing required property: {prop}"
