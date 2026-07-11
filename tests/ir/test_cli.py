"""Tests for CLI `protean ir show` command."""

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from tests.shared import change_working_directory_to

runner = CliRunner()


class TestIRShowJSON:
    """Tests for `protean ir show --format json`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_json_output_is_valid(self):
        change_working_directory_to("test7")
        result = runner.invoke(app, ["ir", "show", "-d", "publishing7.py"])
        assert result.exit_code == 0
        ir = json.loads(result.output)
        assert isinstance(ir, dict)

    def test_json_output_has_top_level_keys(self):
        change_working_directory_to("test7")
        result = runner.invoke(app, ["ir", "show", "-d", "publishing7.py"])
        ir = json.loads(result.output)
        assert "$schema" in ir
        assert "ir_version" in ir
        assert "checksum" in ir
        assert "clusters" in ir
        assert "domain" in ir
        assert "elements" in ir

    def test_json_is_default_format(self):
        change_working_directory_to("test7")
        result = runner.invoke(app, ["ir", "show", "-d", "publishing7.py"])
        # Should parse as JSON without --format flag
        ir = json.loads(result.output)
        assert ir["domain"]["name"] == "TEST7"


class TestIRShowCanonical:
    """Tests for `protean ir show --canonical`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_canonical_omits_generated_at(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "--canonical"]
        )
        assert result.exit_code == 0
        ir = json.loads(result.output)
        assert "generated_at" not in ir

    def test_canonical_retains_content_keys(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "--canonical"]
        )
        ir = json.loads(result.output)
        for key in ("$schema", "ir_version", "checksum", "elements", "domain"):
            assert key in ir, f"canonical output dropped {key!r}"

    def test_default_includes_generated_at(self):
        """Negative control: without --canonical, the timestamp is present."""
        change_working_directory_to("test7")
        result = runner.invoke(app, ["ir", "show", "-d", "publishing7.py"])
        ir = json.loads(result.output)
        assert "generated_at" in ir

    def test_canonical_is_stable_across_runs(self):
        """Two canonical runs of an unchanged domain produce identical output."""
        change_working_directory_to("test7")
        first = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "--canonical"]
        )
        second = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "--canonical"]
        )
        assert first.exit_code == 0
        assert second.exit_code == 0
        assert first.output == second.output

    def test_canonical_is_noop_with_summary_format(self):
        """--canonical has no effect on summary output (documented behavior)."""
        change_working_directory_to("test7")
        result = runner.invoke(
            app,
            ["ir", "show", "-d", "publishing7.py", "-f", "summary", "--canonical"],
        )
        assert result.exit_code == 0
        assert "Domain:" in result.output

    def test_canonical_matches_fix_hook_output(self, tmp_path):
        """`ir show --canonical` and the --fix hook write byte-identical baselines.

        Guards against key-ordering drift between the two baseline writers: a
        user who follows the hook's `ir show` hint and one who lets `--fix`
        regenerate must get the same `.protean/ir.json` bytes.
        """
        from protean.cli.hooks import _regenerate_ir

        change_working_directory_to("test7")
        show_result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "--canonical"]
        )
        _regenerate_ir("publishing7.py", tmp_path / ".protean")
        hook_bytes = (tmp_path / ".protean" / "ir.json").read_text(encoding="utf-8")
        assert show_result.output == hook_bytes


class TestIRShowSummary:
    """Tests for `protean ir show --format summary`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_summary_output_contains_domain_name(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "-f", "summary"]
        )
        assert result.exit_code == 0
        assert "Domain:" in result.output

    def test_summary_output_contains_ir_version(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "-f", "summary"]
        )
        assert "IR Version:" in result.output

    def test_summary_output_contains_checksum(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "-f", "summary"]
        )
        assert "Checksum:" in result.output

    def test_summary_output_contains_element_counts(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "-f", "summary"]
        )
        assert "Element Counts" in result.output


class TestIRShowUpcasters:
    """Upcasters register through the standard lifecycle, so they appear in the
    IR that `protean ir show` renders.

    Asserts against ``load_domain_ir`` (exactly the data `ir show` prints)
    rather than the CliRunner-captured stdout: capturing a subprocess-free
    CLI's stdout is order-fragile in a shared test process, and the `ir show`
    renderer over the elements index is generic and already covered.
    """

    # Absolute path + explicit `:domain`: cwd-independent (this file's other
    # classes chdir) and skips directory-traversal discovery.
    _UPCASTER_DOMAIN = (
        f"{Path(__file__).resolve().parents[1] / 'support' / 'domains' / 'test29' / 'domain29.py'}"
        ":domain"
    )

    def test_upcaster_in_ir_elements_index(self):
        from protean.cli._ir_utils import load_domain_ir

        ir = load_domain_ir(self._UPCASTER_DOMAIN)
        upcasters = ir["elements"].get("UPCASTER", [])
        assert len(upcasters) == 1
        assert any("UpcastOrderPlacedV1ToV2" in fqn for fqn in upcasters)


class TestIRShowErrors:
    """Tests for error handling in `protean ir show`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_invalid_domain_aborts(self):
        change_working_directory_to("test7")
        result = runner.invoke(app, ["ir", "show", "-d", "nonexistent_domain.py"])
        assert result.exit_code != 0
