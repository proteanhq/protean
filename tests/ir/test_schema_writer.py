"""Tests for the schema file writer (``protean.ir.generators.schema_writer``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean.ir.builder import IRBuilder
from protean.ir.generators.schema_writer import (
    _cluster_for_fqn,
    write_all_schemas,
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

    @pytest.mark.parametrize(
        "relative_path",
        [
            "Order/aggregates/Order.v1.json",
            "Order/entities/LineItem.v1.json",
            "Order/value_objects/ShippingAddress.v1.json",
        ],
    )
    def test_element_file_is_written_under_its_cluster_and_kind(self, relative_path):
        assert (self.schemas_dir / relative_path).is_file()

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

    @pytest.mark.parametrize(
        "relative_path",
        [
            "Order/commands/PlaceOrder.v1.json",
            "Order/events/OrderPlaced.v1.json",
            # An aggregate carries no version and defaults to v1.
            "Order/aggregates/Order.v1.json",
        ],
    )
    def test_file_name_carries_the_version(self, relative_path):
        assert (self.schemas_dir / relative_path).is_file()


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

    @pytest.mark.parametrize(
        "relative_path",
        [
            "Order/commands/PlaceOrder.v1.json",
            "Order/events/OrderPlaced.v1.json",
            "Inventory/events/StockReserved.v1.json",
            "Shipment/commands/CreateShipment.v1.json",
        ],
    )
    def test_each_cluster_gets_its_own_directory(self, relative_path):
        assert (self.schemas_dir / relative_path).is_file()


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

    def test_writes_ir_json_into_a_new_nested_directory(self, tmp_path: Path):
        output = tmp_path / "nested" / "deep" / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        path = write_ir(ir, output)

        assert path.name == "ir.json"
        assert path.is_file()
        assert path.is_absolute()
        parsed = json.loads(path.read_text())
        assert "clusters" in parsed
        assert "domain" in parsed

    def test_writes_canonical_baseline(self, tmp_path: Path):
        """`protean schema generate` writes a no-timestamp baseline."""
        output = tmp_path / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        assert "generated_at" in ir  # the source IR carries it ...

        write_ir(ir, output)
        parsed = json.loads((output / "ir.json").read_text())
        assert "generated_at" not in parsed  # ... the baseline drops it
        # Content-derived keys are retained.
        assert "checksum" in parsed

    def test_matches_canonical_serializer(self, tmp_path: Path):
        """write_ir output is byte-identical to the shared canonical form."""
        from protean.ir.constants import canonical_ir_json

        output = tmp_path / ".protean"
        ir = _ir_for(build_cluster_test_domain)
        write_ir(ir, output)

        content = (output / "ir.json").read_text()
        assert content == canonical_ir_json(ir) + "\n"
        # The canonical form is sorted, 2-space indented, with a trailing newline.
        parsed = json.loads(content)
        assert content == json.dumps(parsed, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Unknown FQNs and an empty IR
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestUnknownFqnAndEmptyIR:
    """An unknown FQN maps to no cluster, and an empty IR writes no schema files."""

    @pytest.mark.parametrize(
        "fqn, ir_builder",
        [
            ("nonexistent.Unknown", lambda: _ir_for(build_cluster_test_domain)),
            ("any.Fqn", dict),
        ],
        ids=["unknown-fqn", "empty-ir"],
    )
    def test_cluster_for_fqn_returns_none(self, fqn, ir_builder):
        assert _cluster_for_fqn(fqn, ir_builder()) is None

    def test_write_schemas_empty_ir(self, tmp_path: Path):
        """Empty IR produces no files."""
        output = tmp_path / ".protean"
        written = write_schemas({}, output)
        assert written == []


@pytest.mark.no_test_domain
class TestWriteAllSchemas:
    """`write_all_schemas` emits every format into one tree (the on-ramp)."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path: Path):
        self.output = tmp_path / ".protean"
        self.ir = _ir_for(build_command_event_test_domain)
        self.written = write_all_schemas(self.ir, self.output)
        self.schemas_dir = self.output / "schemas"

    def test_all_three_formats_written(self):
        assert {p.suffix for p in self.written} == {".json", ".avsc", ".proto"}

    def test_formats_coexist_side_by_side(self):
        # p.stem drops only the format extension (.json/.avsc/.proto); .with_name
        # rebuilds siblings without mangling the `.v<N>` segment (which
        # Path.with_suffix would treat as the suffix).
        bases = {p.parent / p.stem for p in self.written}
        assert len(bases) > 0
        for base in bases:
            assert base.with_name(base.name + ".json").exists()
            assert base.with_name(base.name + ".avsc").exists()
            assert base.with_name(base.name + ".proto").exists()

    def test_returns_sorted_paths(self):
        assert self.written == sorted(self.written)

    def test_single_clear_is_idempotent(self):
        rerun = write_all_schemas(self.ir, self.output)
        assert set(rerun) == set(self.written)

    def test_write_schemas_per_format_clobbers_but_write_all_does_not(
        self, tmp_path: Path
    ):
        # Why write_all_schemas exists: write_schemas clears schemas/ on every
        # call, so looping it over formats keeps only the last.
        out = tmp_path / ".protean"
        write_schemas(self.ir, out, fmt="json")
        write_schemas(self.ir, out, fmt="avro")
        assert not list((out / "schemas").rglob("*.json"))  # json clobbered
        assert list((out / "schemas").rglob("*.avsc"))

        write_all_schemas(self.ir, out)
        assert list((out / "schemas").rglob("*.json"))
        assert list((out / "schemas").rglob("*.avsc"))
        assert list((out / "schemas").rglob("*.proto"))

    def test_empty_ir_produces_no_files(self, tmp_path: Path):
        assert write_all_schemas({}, tmp_path / ".protean") == []
