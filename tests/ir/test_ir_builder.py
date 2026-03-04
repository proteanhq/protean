"""Tests for IRBuilder skeleton — domain metadata, checksum, top-level structure."""

import json

import pytest

from protean import Domain
from protean.ir import SCHEMA_VERSION
from protean.ir.builder import IRBuilder


@pytest.mark.no_test_domain
class TestIRTopLevelStructure:
    """Verify the IR dict has all required top-level keys."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.domain = Domain(name="TestDomain")
        self.domain.init(traverse=False)
        self.ir = self.domain.to_ir()

    def test_has_all_required_keys(self):
        required = [
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
        for key in required:
            assert key in self.ir, f"Missing required key: {key}"

    def test_schema_uri(self):
        assert (
            self.ir["$schema"]
            == f"https://protean.dev/ir/v{SCHEMA_VERSION}/schema.json"
        )

    def test_ir_version(self):
        assert self.ir["ir_version"] == SCHEMA_VERSION

    def test_generated_at_format(self):
        # ISO 8601 UTC timestamp ending with Z
        ts = self.ir["generated_at"]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_contracts_section_present(self):
        assert "contracts" in self.ir
        assert "events" in self.ir["contracts"]

    def test_flows_subsections(self):
        flows = self.ir["flows"]
        assert "domain_services" in flows
        assert "process_managers" in flows
        assert "subscribers" in flows


@pytest.mark.no_test_domain
class TestDomainMetadata:
    """Verify domain metadata extraction."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.domain = Domain(name="My Ordering Service")
        self.domain.init(traverse=False)
        self.ir = self.domain.to_ir()

    def test_name(self):
        assert self.ir["domain"]["name"] == "My Ordering Service"

    def test_normalized_name(self):
        assert self.ir["domain"]["normalized_name"] == "my_ordering_service"

    def test_camel_case_name(self):
        assert self.ir["domain"]["camel_case_name"] == "MyOrderingService"

    def test_identity_strategy_default(self):
        assert self.ir["domain"]["identity_strategy"] == "uuid"

    def test_identity_type_default(self):
        assert self.ir["domain"]["identity_type"] == "string"

    def test_event_processing_present(self):
        assert self.ir["domain"]["event_processing"] in ("sync", "async")

    def test_command_processing_present(self):
        assert self.ir["domain"]["command_processing"] in ("sync", "async")

    def test_metadata_keys_sorted_alphabetically(self):
        keys = list(self.ir["domain"].keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestChecksum:
    """Verify checksum computation and determinism."""

    def test_checksum_format(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        ir = domain.to_ir()
        assert ir["checksum"].startswith("sha256:")
        assert len(ir["checksum"]) == 71  # "sha256:" + 64 hex chars

    def test_checksum_deterministic(self):
        """Two builds of the same domain should produce the same checksum."""
        domain = Domain(name="Determinism")
        domain.init(traverse=False)

        ir1 = domain.to_ir()
        ir2 = domain.to_ir()

        # Normalize generated_at for comparison
        ir1_copy = {k: v for k, v in ir1.items() if k != "generated_at"}
        ir2_copy = {k: v for k, v in ir2.items() if k != "generated_at"}

        assert json.dumps(ir1_copy, sort_keys=True) == json.dumps(
            ir2_copy, sort_keys=True
        )
        assert ir1["checksum"] == ir2["checksum"]

    def test_checksum_changes_with_content(self):
        """Different domain names should produce different checksums."""
        d1 = Domain(name="Alpha")
        d1.init(traverse=False)
        d2 = Domain(name="Beta")
        d2.init(traverse=False)
        assert d1.to_ir()["checksum"] != d2.to_ir()["checksum"]


@pytest.mark.no_test_domain
class TestIRBuilderDirect:
    """Test IRBuilder can be used directly."""

    def test_builder_produces_same_as_domain_method(self):
        domain = Domain(name="Direct")
        domain.init(traverse=False)
        ir_via_method = domain.to_ir()
        ir_via_builder = IRBuilder(domain).build()

        # Normalize timestamps for comparison
        ir_via_method.pop("generated_at")
        ir_via_builder.pop("generated_at")
        ir_via_method.pop("checksum")
        ir_via_builder.pop("checksum")

        assert ir_via_method == ir_via_builder
