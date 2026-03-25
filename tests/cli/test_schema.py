"""Tests for ``protean schema`` CLI commands.

Covers ``protean schema generate`` and ``protean schema show`` with
all flags, error handling, and output verification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from typer.testing import CliRunner

from protean.cli.schema import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Minimal IR fixture
# ---------------------------------------------------------------------------


def _minimal_ir() -> dict[str, Any]:
    """Return a minimal IR with one aggregate and one event."""
    return {
        "ir_version": "1.0",
        "domain": {"name": "TestDomain"},
        "checksum": "abc123",
        "elements": {},
        "clusters": {
            "test.Order": {
                "aggregate": {
                    "name": "Order",
                    "fqn": "test.Order",
                    "element_type": "AGGREGATE",
                    "fields": {
                        "id": {
                            "kind": "auto",
                            "type": "Auto",
                            "identifier": True,
                            "required": True,
                        },
                        "customer_name": {
                            "kind": "standard",
                            "type": "String",
                            "max_length": 100,
                            "required": True,
                        },
                    },
                    "identity_field": "id",
                    "options": {},
                },
                "entities": {},
                "value_objects": {},
                "commands": {},
                "events": {
                    "test.OrderPlaced": {
                        "name": "OrderPlaced",
                        "fqn": "test.OrderPlaced",
                        "element_type": "EVENT",
                        "__version__": 1,
                        "__type__": "Test.OrderPlaced.v1",
                        "part_of": "test.Order",
                        "fields": {
                            "order_id": {
                                "kind": "standard",
                                "type": "Identifier",
                                "required": True,
                            },
                        },
                    },
                },
                "command_handlers": {},
                "event_handlers": {},
                "repositories": {},
                "database_models": {},
                "application_services": {},
            },
        },
        "projections": {},
        "flows": {
            "domain_services": {},
            "process_managers": {},
            "subscribers": {},
        },
        "diagnostics": [],
    }


# ---------------------------------------------------------------------------
# ``protean schema`` — no-args help
# ---------------------------------------------------------------------------


class TestSchemaNoArgs:
    def test_no_args_shows_help(self):
        result = runner.invoke(app)
        assert result.exit_code == 2

    def test_help_flag(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "generate" in result.output
        assert "show" in result.output


# ---------------------------------------------------------------------------
# ``protean schema generate`` — input validation
# ---------------------------------------------------------------------------


class TestSchemaGenerateValidation:
    def test_no_domain_no_ir_aborts(self):
        result = runner.invoke(app, ["generate"])
        assert result.exit_code != 0
        assert "provide either --domain or --ir" in result.output

    def test_both_domain_and_ir_aborts(self):
        result = runner.invoke(app, ["generate", "--domain=x", "--ir=y"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output


# ---------------------------------------------------------------------------
# ``protean schema generate`` — from IR file
# ---------------------------------------------------------------------------


class TestSchemaGenerateFromIR:
    def test_generate_from_ir_file(self, tmp_path: Path):
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(_minimal_ir()), encoding="utf-8")
        output_dir = tmp_path / "output"

        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", f"--output={output_dir}"],
        )
        assert result.exit_code == 0
        assert "Wrote" in result.output
        assert "schema files" in result.output

        # Verify schema files were written
        schemas_dir = output_dir / "schemas"
        assert schemas_dir.exists()

        # Verify IR was written
        ir_out = output_dir / "ir.json"
        assert ir_out.exists()

    def test_generate_from_nonexistent_ir_aborts(self):
        result = runner.invoke(app, ["generate", "--ir=/nonexistent/path.json"])
        assert result.exit_code != 0

    def test_generate_default_output_directory(self, tmp_path: Path, monkeypatch):
        """Without --output, schemas are written to .protean/ under cwd."""
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(_minimal_ir()), encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            ["generate", f"--ir={ir_file}"],
        )
        assert result.exit_code == 0

        # Verify default .protean/ directory was created
        assert (tmp_path / ".protean" / "schemas").exists()
        assert (tmp_path / ".protean" / "ir.json").exists()

    def test_generate_writes_valid_json_schemas(self, tmp_path: Path):
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(_minimal_ir()), encoding="utf-8")
        output_dir = tmp_path / "output"

        runner.invoke(
            app,
            ["generate", f"--ir={ir_file}", f"--output={output_dir}"],
        )

        # All .json files in schemas/ should be valid JSON
        schemas_dir = output_dir / "schemas"
        for json_file in schemas_dir.rglob("*.json"):
            data = json.loads(json_file.read_text(encoding="utf-8"))
            assert "$schema" in data
            assert data["type"] == "object"


# ---------------------------------------------------------------------------
# ``protean schema show`` — input validation
# ---------------------------------------------------------------------------


class TestSchemaShowValidation:
    def test_no_domain_no_ir_aborts(self):
        result = runner.invoke(app, ["show", "Order"])
        assert result.exit_code != 0
        assert "provide either --domain or --ir" in result.output

    def test_both_domain_and_ir_aborts(self):
        result = runner.invoke(app, ["show", "Order", "--domain=x", "--ir=y"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output


# ---------------------------------------------------------------------------
# ``protean schema show`` — element lookup
# ---------------------------------------------------------------------------


class TestSchemaShowLookup:
    def test_show_by_short_name(self, tmp_path: Path):
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(_minimal_ir()), encoding="utf-8")

        result = runner.invoke(app, ["show", "Order", f"--ir={ir_file}", "--raw"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Order"
        assert data["type"] == "object"

    def test_show_by_fqn(self, tmp_path: Path):
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(_minimal_ir()), encoding="utf-8")

        result = runner.invoke(app, ["show", "test.Order", f"--ir={ir_file}", "--raw"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "Order"

    def test_show_event_by_name(self, tmp_path: Path):
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(_minimal_ir()), encoding="utf-8")

        result = runner.invoke(app, ["show", "OrderPlaced", f"--ir={ir_file}", "--raw"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "OrderPlaced"
        assert data["x-protean-element-type"] == "event"

    def test_show_nonexistent_element_aborts(self, tmp_path: Path):
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(_minimal_ir()), encoding="utf-8")

        result = runner.invoke(app, ["show", "DoesNotExist", f"--ir={ir_file}"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_show_disambiguation(self, tmp_path: Path):
        """When multiple elements match by short name, list FQNs."""
        ir = _minimal_ir()
        # Add a second cluster with another "Order" aggregate
        ir["clusters"]["other.Order"] = {
            "aggregate": {
                "name": "Order",
                "fqn": "other.Order",
                "element_type": "AGGREGATE",
                "fields": {
                    "id": {
                        "kind": "auto",
                        "type": "Auto",
                        "identifier": True,
                        "required": True,
                    },
                },
                "identity_field": "id",
                "options": {},
            },
            "entities": {},
            "value_objects": {},
            "commands": {},
            "events": {},
            "command_handlers": {},
            "event_handlers": {},
            "repositories": {},
            "database_models": {},
            "application_services": {},
        }

        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(ir), encoding="utf-8")

        result = runner.invoke(app, ["show", "Order", f"--ir={ir_file}"])
        assert result.exit_code != 0
        assert "Multiple elements" in result.output
        assert "test.Order" in result.output
        assert "other.Order" in result.output

    def test_show_pretty_print_default(self, tmp_path: Path):
        """Without --raw, output uses syntax highlighting (no pure JSON)."""
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(_minimal_ir()), encoding="utf-8")

        result = runner.invoke(app, ["show", "Order", f"--ir={ir_file}"])
        assert result.exit_code == 0
        # Pretty-printed output contains the schema content
        assert "Order" in result.output

    def test_show_raw_is_valid_json(self, tmp_path: Path):
        """--raw flag outputs valid JSON that can be piped."""
        ir_file = tmp_path / "test-ir.json"
        ir_file.write_text(json.dumps(_minimal_ir()), encoding="utf-8")

        result = runner.invoke(app, ["show", "Order", f"--ir={ir_file}", "--raw"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)
