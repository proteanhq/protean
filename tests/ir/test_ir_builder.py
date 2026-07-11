"""Tests for IRBuilder skeleton — domain metadata, checksum, top-level structure."""

import json

import pytest

from protean import Domain
from protean.ir import SCHEMA_VERSION
from protean.ir.builder import IRBuilder
from protean.ir.constants import (
    CANONICAL_EXCLUDED_KEYS,
    VOLATILE_IR_KEYS,
    canonical_ir,
    canonical_ir_json,
)
from protean.ir.diff import diff_ir


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

    def test_checksum_ignores_every_volatile_key(self):
        """Mutating *any* volatile/derived key must not change the checksum.

        Regression guard: ``ir check`` (staleness) reported a domain as
        stale on a framework-version-only difference while ``ir diff`` reported
        no changes. The checksum must reflect domain *content* only. Drives the
        full exclusion set from ``VOLATILE_IR_KEYS`` so it can't silently miss a
        key (e.g. ``elements``/``checksum``).
        """
        domain = Domain(name="Volatile")
        domain.init(traverse=False)
        ir = domain.to_ir()
        baseline = IRBuilder._compute_checksum(ir)

        sentinels = {
            "$schema": "https://protean.dev/ir/v9.9.9/schema.json",
            "ir_version": "9.9.9",
            "generated_at": "2099-01-01T00:00:00Z",
            "checksum": "sha256:deadbeef",
            "elements": {"mutated": True},
        }
        # Every excluded key has a sentinel value to mutate.
        assert set(sentinels) == set(VOLATILE_IR_KEYS)

        for key, value in sentinels.items():
            bumped = dict(ir)
            bumped[key] = value
            assert IRBuilder._compute_checksum(bumped) == baseline, (
                f"checksum changed when only volatile key {key!r} was mutated"
            )

    def test_checksum_and_diff_agree_on_volatile_only_change(self):
        """A framework-version-only difference is not a change to either path.

        Enforces the lockstep across both code paths (``diff_ir`` and the
        staleness checksum) using the shared exclusion set.
        """
        domain = Domain(name="Lockstep")
        domain.init(traverse=False)
        ir = domain.to_ir()

        bumped = dict(ir)
        bumped["ir_version"] = "9.9.9"
        bumped["$schema"] = "https://protean.dev/ir/v9.9.9/schema.json"
        bumped["generated_at"] = "2099-01-01T00:00:00Z"

        # ir diff sees no change ...
        assert diff_ir(ir, bumped)["summary"]["has_changes"] is False
        # ... and the staleness checksum agrees.
        assert IRBuilder._compute_checksum(bumped) == IRBuilder._compute_checksum(ir)


@pytest.mark.no_test_domain
class TestCanonicalIR:
    """Tests for ``canonical_ir`` — the no-timestamp baseline output."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.domain = Domain(name="Canonical")
        self.domain.init(traverse=False)
        self.ir = self.domain.to_ir()

    def test_strips_only_generated_at(self):
        assert frozenset({"generated_at"}) == CANONICAL_EXCLUDED_KEYS
        canonical = canonical_ir(self.ir)
        assert "generated_at" not in canonical
        # Readable/content-derived keys are retained.
        for key in ("$schema", "ir_version", "checksum", "elements"):
            assert key in canonical, f"canonical output dropped {key!r}"

    def test_does_not_mutate_input(self):
        canonical_ir(self.ir)
        assert "generated_at" in self.ir

    def test_stable_across_regenerations(self):
        """A canonical baseline only changes when the contract changes.

        Two builds of the same domain differ only in ``generated_at``; their
        canonical forms must be byte-for-byte identical.
        """
        ir2 = self.domain.to_ir()
        ir2["generated_at"] = "2099-01-01T00:00:00Z"
        assert ir2 != self.ir  # timestamps differ
        assert canonical_ir(ir2) == canonical_ir(self.ir)

    def test_checksum_survives_canonicalization(self):
        """Staleness reads ``checksum`` from the baseline — it must persist."""
        assert canonical_ir(self.ir)["checksum"] == self.ir["checksum"]

    def test_diff_sees_no_change_between_canonical_and_full(self):
        """A canonical baseline (no timestamp) vs live IR (with one): no diff."""
        assert (
            diff_ir(canonical_ir(self.ir), self.ir)["summary"]["has_changes"] is False
        )

    def test_json_is_sorted_and_deterministic(self):
        """The serializer sorts keys and omits generated_at, stable across builds."""
        text = canonical_ir_json(self.ir)
        assert "generated_at" not in json.loads(text)
        # Keys are sorted (deterministic byte layout, no ordering churn).
        assert json.dumps(json.loads(text), indent=2, sort_keys=True) == text
        # Two builds of the same domain serialize identically.
        assert canonical_ir_json(self.domain.to_ir()) == text


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
