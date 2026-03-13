"""Tests for the schema file writer (``protean.ir.generators.schema_writer``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean.ir.builder import IRBuilder
from protean.ir.generators.schema_writer import (
    _cluster_for_fqn,
    _element_version,
    write_ir,
    write_schemas,
)

from .elements import (
    build_cluster_test_domain,
    build_command_event_test_domain,
    build_integration_domain,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ir_for(builder_fn):
    """Build the IR dict from a domain builder function."""
    domain = builder_fn()
    return IRBuilder(domain).build()


# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDirectoryStructure:
    """Verify the generated directory layout matches the convention."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path: Path):
        self.output = tmp_path / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        self.written = write_schemas(ir, self.output)
        self.schemas_dir = self.output / "schemas"

    def test_schemas_directory_created(self):
        assert self.schemas_dir.is_dir()

    def test_cluster_directory_exists(self):
        assert (self.schemas_dir / "Order").is_dir()

    def test_aggregates_subdir(self):
        assert (self.schemas_dir / "Order" / "aggregates").is_dir()

    def test_entities_subdir(self):
        assert (self.schemas_dir / "Order" / "entities").is_dir()

    def test_value_objects_subdir(self):
        assert (self.schemas_dir / "Order" / "value_objects").is_dir()

    def test_aggregate_file_exists(self):
        agg_file = self.schemas_dir / "Order" / "aggregates" / "Order.v1.json"
        assert agg_file.is_file()

    def test_entity_file_exists(self):
        ent_file = self.schemas_dir / "Order" / "entities" / "LineItem.v1.json"
        assert ent_file.is_file()

    def test_value_object_file_exists(self):
        vo_file = (
            self.schemas_dir / "Order" / "value_objects" / "ShippingAddress.v1.json"
        )
        assert vo_file.is_file()

    def test_returns_sorted_paths(self):
        assert self.written == sorted(self.written)

    def test_returns_absolute_paths(self):
        for p in self.written:
            assert p.is_absolute()


# ---------------------------------------------------------------------------
# Commands and events with versioning
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCommandEventVersioning:
    """Verify filename versioning for commands and events."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path: Path):
        self.output = tmp_path / ".protean"
        ir = _ir_for(build_command_event_test_domain)
        self.written = write_schemas(ir, self.output)
        self.schemas_dir = self.output / "schemas"

    def test_commands_subdir_exists(self):
        assert (self.schemas_dir / "Order" / "commands").is_dir()

    def test_events_subdir_exists(self):
        assert (self.schemas_dir / "Order" / "events").is_dir()

    def test_command_file_versioned(self):
        cmd_file = self.schemas_dir / "Order" / "commands" / "PlaceOrder.v1.json"
        assert cmd_file.is_file()

    def test_event_file_versioned(self):
        evt_file = self.schemas_dir / "Order" / "events" / "OrderPlaced.v1.json"
        assert evt_file.is_file()

    def test_non_versioned_elements_default_to_v1(self):
        agg_file = self.schemas_dir / "Order" / "aggregates" / "Order.v1.json"
        assert agg_file.is_file()


# ---------------------------------------------------------------------------
# Multi-cluster domains
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestMultiClusterDomain:
    """Verify directory structure for domains with multiple aggregates."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path: Path):
        self.output = tmp_path / ".protean"
        ir = _ir_for(build_integration_domain)
        self.written = write_schemas(ir, self.output)
        self.schemas_dir = self.output / "schemas"

    def test_order_cluster_exists(self):
        assert (self.schemas_dir / "Order").is_dir()

    def test_inventory_cluster_exists(self):
        assert (self.schemas_dir / "Inventory").is_dir()

    def test_shipment_cluster_exists(self):
        assert (self.schemas_dir / "Shipment").is_dir()

    def test_order_has_commands(self):
        assert (self.schemas_dir / "Order" / "commands" / "PlaceOrder.v1.json").is_file()

    def test_order_has_events(self):
        assert (self.schemas_dir / "Order" / "events" / "OrderPlaced.v1.json").is_file()

    def test_inventory_has_events(self):
        assert (
            self.schemas_dir / "Inventory" / "events" / "StockReserved.v1.json"
        ).is_file()

    def test_shipment_has_commands(self):
        assert (
            self.schemas_dir / "Shipment" / "commands" / "CreateShipment.v1.json"
        ).is_file()


# ---------------------------------------------------------------------------
# Projections placement
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestProjectionsPlacement:
    """Verify projections go under top-level ``projections/`` directory."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path: Path):
        self.output = tmp_path / ".protean"
        ir = _ir_for(build_integration_domain)
        self.written = write_schemas(ir, self.output)
        self.schemas_dir = self.output / "schemas"

    def test_projections_directory_exists(self):
        assert (self.schemas_dir / "projections").is_dir()

    def test_projection_file_exists(self):
        proj_file = self.schemas_dir / "projections" / "OrderDashboard.v1.json"
        assert proj_file.is_file()

    def test_projection_not_in_cluster_dirs(self):
        """Projections should not appear inside aggregate cluster directories."""
        for cluster_dir in self.schemas_dir.iterdir():
            if cluster_dir.name == "projections":
                continue
            if cluster_dir.is_dir():
                proj_dir = cluster_dir / "projections"
                if proj_dir.exists():
                    assert not list(proj_dir.iterdir())


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDeterminism:
    """Verify byte-identical output on re-run."""

    def test_identical_output_on_rerun(self, tmp_path: Path):
        ir = _ir_for(build_cluster_test_domain)

        out1 = tmp_path / "run1"
        out2 = tmp_path / "run2"

        write_schemas(ir, out1)
        write_schemas(ir, out2)

        files1 = sorted(
            (p.relative_to(out1), p.read_text()) for p in out1.rglob("*.json")
        )
        files2 = sorted(
            (p.relative_to(out2), p.read_text()) for p in out2.rglob("*.json")
        )

        assert files1 == files2

    def test_same_filenames_on_rerun(self, tmp_path: Path):
        ir = _ir_for(build_integration_domain)

        out1 = tmp_path / "run1"
        out2 = tmp_path / "run2"

        paths1 = write_schemas(ir, out1)
        paths2 = write_schemas(ir, out2)

        # Relative paths should match
        rel1 = sorted(p.relative_to(out1.resolve()) for p in paths1)
        rel2 = sorted(p.relative_to(out2.resolve()) for p in paths2)
        assert rel1 == rel2


# ---------------------------------------------------------------------------
# Clean re-generation
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCleanRegeneration:
    """Verify that re-running clears stale files."""

    def test_stale_files_removed(self, tmp_path: Path):
        output = tmp_path / ".protean"
        schemas_dir = output / "schemas"

        # Create a stale file
        stale_dir = schemas_dir / "StaleCluster" / "aggregates"
        stale_dir.mkdir(parents=True)
        stale_file = stale_dir / "Stale.v1.json"
        stale_file.write_text("{}")

        # Run writer
        ir = _ir_for(build_cluster_test_domain)
        write_schemas(ir, output)

        # Stale file should be gone
        assert not stale_file.exists()
        assert not (schemas_dir / "StaleCluster").exists()


# ---------------------------------------------------------------------------
# File content validity
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestFileContent:
    """Verify written file contents are valid JSON Schema."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path: Path):
        self.output = tmp_path / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        write_schemas(ir, self.output)
        self.schemas_dir = self.output / "schemas"

    def test_files_are_valid_json(self):
        for json_file in self.schemas_dir.rglob("*.json"):
            content = json_file.read_text()
            parsed = json.loads(content)
            assert isinstance(parsed, dict)

    def test_files_have_trailing_newline(self):
        for json_file in self.schemas_dir.rglob("*.json"):
            content = json_file.read_text()
            assert content.endswith("\n")

    def test_files_have_sorted_keys(self):
        for json_file in self.schemas_dir.rglob("*.json"):
            content = json_file.read_text()
            parsed = json.loads(content)
            reserialized = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
            assert content == reserialized

    def test_aggregate_schema_has_expected_keys(self):
        agg_file = self.schemas_dir / "Order" / "aggregates" / "Order.v1.json"
        schema = json.loads(agg_file.read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert "properties" in schema
        assert schema["x-protean-element-type"] == "aggregate"


# ---------------------------------------------------------------------------
# write_ir
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestWriteIR:
    """Verify ``write_ir()`` writes a valid ``ir.json``."""

    def test_writes_ir_json(self, tmp_path: Path):
        output = tmp_path / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        path = write_ir(ir, output)

        assert path.name == "ir.json"
        assert path.is_file()

    def test_ir_json_is_valid(self, tmp_path: Path):
        output = tmp_path / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        write_ir(ir, output)

        content = (output / "ir.json").read_text()
        parsed = json.loads(content)
        assert "clusters" in parsed
        assert "domain" in parsed

    def test_ir_json_has_trailing_newline(self, tmp_path: Path):
        output = tmp_path / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        write_ir(ir, output)

        content = (output / "ir.json").read_text()
        assert content.endswith("\n")

    def test_ir_json_sorted_keys(self, tmp_path: Path):
        output = tmp_path / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        write_ir(ir, output)

        content = (output / "ir.json").read_text()
        parsed = json.loads(content)
        reserialized = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
        assert content == reserialized

    def test_creates_output_dir_if_missing(self, tmp_path: Path):
        output = tmp_path / "nested" / "deep" / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        path = write_ir(ir, output)

        assert path.is_file()

    def test_returns_absolute_path(self, tmp_path: Path):
        output = tmp_path / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        path = write_ir(ir, output)

        assert path.is_absolute()


# ---------------------------------------------------------------------------
# Helper function edge cases
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestHelperEdgeCases:
    """Cover edge cases in helper functions."""

    def test_cluster_for_fqn_returns_none_for_unknown(self):
        ir = _ir_for(build_cluster_test_domain)
        result = _cluster_for_fqn("nonexistent.Unknown", ir)
        assert result is None

    def test_cluster_for_fqn_empty_ir(self):
        result = _cluster_for_fqn("any.Fqn", {})
        assert result is None

    def test_element_version_defaults_to_one(self):
        assert _element_version({}) == 1

    def test_element_version_reads_extension(self):
        assert _element_version({"x-protean-version": 3}) == 3

    def test_write_schemas_empty_ir(self, tmp_path: Path):
        """Empty IR produces no files."""
        output = tmp_path / ".protean"
        written = write_schemas({}, output)
        assert written == []
