"""Tests that example IR files validate against the schema structure."""

import json
from pathlib import Path

import pytest

from protean.ir import EXAMPLES_DIR


def _example_files():
    """Yield parametrized paths for each example JSON file."""
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        yield pytest.param(path, id=path.stem)


@pytest.mark.no_test_domain
class TestExamplesExist:
    def test_examples_directory_exists(self):
        assert EXAMPLES_DIR.exists()

    def test_at_least_two_examples(self):
        examples = list(EXAMPLES_DIR.glob("*.json"))
        assert len(examples) >= 2


@pytest.mark.no_test_domain
class TestExampleStructure:
    """Validate examples have the expected top-level keys and metadata."""

    @pytest.mark.parametrize("example_path", _example_files())
    def test_example_is_valid_json(self, example_path: Path):
        data = json.loads(example_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    @pytest.mark.parametrize("example_path", _example_files())
    def test_example_has_required_keys(self, example_path: Path):
        data = json.loads(example_path.read_text(encoding="utf-8"))
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
            assert key in data, f"{example_path.name} missing required key: {key}"

    @pytest.mark.parametrize("example_path", _example_files())
    def test_example_ir_version(self, example_path: Path):
        data = json.loads(example_path.read_text(encoding="utf-8"))
        assert data["ir_version"] == "0.1.0"

    @pytest.mark.parametrize("example_path", _example_files())
    def test_example_checksum_format(self, example_path: Path):
        data = json.loads(example_path.read_text(encoding="utf-8"))
        checksum = data["checksum"]
        assert checksum.startswith("sha256:"), "Checksum must start with 'sha256:'"
        assert len(checksum) == 71, (
            f"Expected 71 chars (sha256: + 64 hex), got {len(checksum)}"
        )

    @pytest.mark.parametrize("example_path", _example_files())
    def test_example_has_at_least_one_cluster(self, example_path: Path):
        data = json.loads(example_path.read_text(encoding="utf-8"))
        assert len(data["clusters"]) >= 1

    @pytest.mark.parametrize("example_path", _example_files())
    def test_example_elements_index_present(self, example_path: Path):
        data = json.loads(example_path.read_text(encoding="utf-8"))
        elements = data["elements"]
        assert "AGGREGATE" in elements
        assert "COMMAND" in elements
        assert "EVENT" in elements
