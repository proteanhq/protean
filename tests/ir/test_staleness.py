"""Tests for IR staleness detection — src/protean/ir/staleness.py and `protean ir check` CLI."""

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.ir import SCHEMA_VERSION
from protean.ir.config import CompatConfig
from protean.ir.staleness import (
    StalenessResult,
    StalenessStatus,
    check_staleness,
    load_stored_ir,
)
from tests.shared import change_working_directory_to

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_ir(directory: Path, ir_dict: dict) -> Path:
    """Write *ir_dict* as ir.json into *directory* and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ir.json"
    path.write_text(json.dumps(ir_dict, indent=2), encoding="utf-8")
    return path


def _live_ir_for_test7() -> dict:
    """Return the live IR dict for the test7 domain (publishing7.py).

    Caller is responsible for setting the working directory to test7
    before calling this.
    """
    from protean.ir.builder import IRBuilder
    from protean.utils.domain_discovery import derive_domain

    domain = derive_domain("publishing7.py")
    domain.init()
    return IRBuilder(domain).build()


# ---------------------------------------------------------------------------
# TestLoadStoredIr
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestLoadStoredIr:
    """Unit tests for load_stored_ir()."""

    def test_returns_none_when_no_file(self, tmp_path):
        result = load_stored_ir(tmp_path)
        assert result is None

    def test_returns_ir_dict_and_path_for_valid_file(self, tmp_path):
        ir = {"ir_version": "0.1.0", "checksum": "sha256:abc123", "clusters": {}}
        _write_ir(tmp_path, ir)

        result = load_stored_ir(tmp_path)

        assert result is not None
        ir_dict, ir_path = result
        assert ir_dict == ir
        assert ir_path == tmp_path / "ir.json"

    def test_raises_for_invalid_json(self, tmp_path):
        bad = tmp_path / "ir.json"
        bad.write_text("{ not valid json", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid JSON"):
            load_stored_ir(tmp_path)

    def test_accepts_str_path(self, tmp_path):
        ir = {"checksum": "sha256:xyz"}
        _write_ir(tmp_path, ir)

        result = load_stored_ir(str(tmp_path))

        assert result is not None
        ir_dict, _ = result
        assert ir_dict == ir

    def test_returns_none_for_missing_directory(self, tmp_path):
        missing = tmp_path / "nonexistent"
        result = load_stored_ir(missing)
        assert result is None

    def test_raises_for_unreadable_file(self, tmp_path):
        # Make ir.json a directory so read_text raises IsADirectoryError (OSError subclass)
        ir_dir = tmp_path / "ir.json"
        ir_dir.mkdir()

        with pytest.raises(ValueError, match="Could not read"):
            load_stored_ir(tmp_path)


# ---------------------------------------------------------------------------
# TestStalenessResult
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestStalenessResult:
    """Unit tests for the StalenessResult dataclass and StalenessStatus enum."""

    def test_status_values(self):
        assert StalenessStatus.FRESH.value == "fresh"
        assert StalenessStatus.STALE.value == "stale"
        assert StalenessStatus.NO_IR.value == "no_ir"
        assert StalenessStatus.VERSION_MISMATCH.value == "version_mismatch"

    def test_version_fields_default_to_none(self):
        result = StalenessResult(
            status=StalenessStatus.STALE,
            domain_checksum="sha256:new",
            stored_checksum="sha256:old",
            ir_file=None,
        )
        assert result.stored_version is None
        assert result.current_version is None

    def test_result_is_frozen(self):
        result = StalenessResult(
            status=StalenessStatus.FRESH,
            domain_checksum="sha256:abc",
            stored_checksum="sha256:abc",
            ir_file=Path("/tmp/ir.json"),
        )
        with pytest.raises(Exception):
            result.status = StalenessStatus.STALE  # type: ignore[misc]

    def test_result_fields(self):
        path = Path("/some/.protean/ir.json")
        result = StalenessResult(
            status=StalenessStatus.STALE,
            domain_checksum="sha256:new",
            stored_checksum="sha256:old",
            ir_file=path,
        )
        assert result.status == StalenessStatus.STALE
        assert result.domain_checksum == "sha256:new"
        assert result.stored_checksum == "sha256:old"
        assert result.ir_file == path

    def test_no_ir_result_has_none_fields(self):
        result = StalenessResult(
            status=StalenessStatus.NO_IR,
            domain_checksum=None,
            stored_checksum=None,
            ir_file=None,
        )
        assert result.domain_checksum is None
        assert result.stored_checksum is None
        assert result.ir_file is None


# ---------------------------------------------------------------------------
# TestCheckStaleness — function-level tests using a real domain file
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckStalenessFresh:
    """check_staleness() returns FRESH when the stored checksum matches."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_fresh_when_checksums_match(self):
        live_ir = _live_ir_for_test7()
        _write_ir(self._protean_dir, live_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.FRESH

    def test_raises_when_derive_domain_returns_none(self, monkeypatch):
        """A stored IR present but no derivable domain must raise, not crash.

        Guards against calling .init() on a None domain (derive_domain is
        typed Domain | None).
        """
        from protean.exceptions import NoDomainException

        _write_ir(self._protean_dir, _live_ir_for_test7())
        monkeypatch.setattr("protean.ir.staleness.derive_domain", lambda _: None)

        with pytest.raises(NoDomainException):
            check_staleness("publishing7.py", self._protean_dir)

    def test_fresh_result_has_matching_checksums(self):
        live_ir = _live_ir_for_test7()
        _write_ir(self._protean_dir, live_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.domain_checksum == live_ir["checksum"]
        assert result.stored_checksum == live_ir["checksum"]
        assert result.domain_checksum == result.stored_checksum

    def test_fresh_result_has_ir_file_path(self):
        live_ir = _live_ir_for_test7()
        _write_ir(self._protean_dir, live_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.ir_file is not None
        assert result.ir_file.name == "ir.json"


@pytest.mark.no_test_domain
class TestShowAndCheckProduceSameChecksum:
    """``protean ir show`` and ``check_staleness()`` must use the same
    domain initialization so their checksums agree.

    Regression test for https://github.com/proteanhq/protean/issues/835
    """

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_ir_show_output_is_fresh_according_to_check(self):
        """Write IR via the same path as ``protean ir show``, then verify
        ``check_staleness`` considers it fresh."""
        from protean.cli._ir_utils import load_domain_ir

        show_ir = load_domain_ir("publishing7.py")
        _write_ir(self._protean_dir, show_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.FRESH
        assert result.domain_checksum == show_ir["checksum"]

    def test_checksums_match_between_show_and_staleness(self):
        """Directly compare checksums from ``load_domain_ir`` (show path)
        and ``check_staleness`` (check path)."""
        from protean.cli._ir_utils import load_domain_ir

        show_ir = load_domain_ir("publishing7.py")
        _write_ir(self._protean_dir, show_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.domain_checksum == show_ir["checksum"]
        assert result.stored_checksum == show_ir["checksum"]


@pytest.mark.no_test_domain
class TestCheckStalenessStale:
    """check_staleness() returns STALE when checksums differ."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_stale_when_checksum_differs(self):
        stale_ir = {"checksum": "sha256:outdated000000000000000000000000"}
        _write_ir(self._protean_dir, stale_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.STALE

    def test_stale_result_has_different_checksums(self):
        stale_ir = {"checksum": "sha256:outdated000000000000000000000000"}
        _write_ir(self._protean_dir, stale_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.domain_checksum != result.stored_checksum
        assert result.stored_checksum == "sha256:outdated000000000000000000000000"
        assert result.domain_checksum is not None

    def test_stale_result_has_ir_file_path(self):
        stale_ir = {"checksum": "sha256:outdated000000000000000000000000"}
        _write_ir(self._protean_dir, stale_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.ir_file is not None


@pytest.mark.no_test_domain
class TestCheckStalenessNoIR:
    """check_staleness() returns NO_IR when no ir.json exists."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._empty_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_no_ir_when_directory_empty(self):
        # Directory not even created — no ir.json
        result = check_staleness("publishing7.py", self._empty_dir)

        assert result.status == StalenessStatus.NO_IR

    def test_no_ir_result_has_none_checksums(self):
        result = check_staleness("publishing7.py", self._empty_dir)

        assert result.domain_checksum is None
        assert result.stored_checksum is None
        assert result.ir_file is None

    def test_no_ir_with_str_path(self):
        result = check_staleness("publishing7.py", str(self._empty_dir))

        assert result.status == StalenessStatus.NO_IR


# ---------------------------------------------------------------------------
# TestCheckStalenessVersionMismatch — schema version discipline
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckStalenessVersionMismatch:
    """check_staleness() distinguishes an older-schema baseline from stale content."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_version_mismatch_when_stored_version_differs(self):
        # Older schema version → VERSION_MISMATCH, regardless of checksum.
        _write_ir(
            self._protean_dir,
            {"ir_version": "0.0.9", "checksum": "sha256:whatever"},
        )

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.VERSION_MISMATCH

    def test_version_mismatch_populates_versions(self):
        _write_ir(
            self._protean_dir,
            {"ir_version": "0.0.9", "checksum": "sha256:whatever"},
        )

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.stored_version == "0.0.9"
        assert result.current_version == SCHEMA_VERSION
        assert result.stored_checksum == "sha256:whatever"
        assert result.ir_file is not None

    def test_version_mismatch_when_stored_version_is_newer(self):
        # The branch fires on ANY version difference, not only older baselines.
        _write_ir(
            self._protean_dir,
            {"ir_version": "9.9.9", "checksum": "sha256:whatever"},
        )

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.VERSION_MISMATCH
        assert result.stored_version == "9.9.9"
        assert result.current_version == SCHEMA_VERSION

    def test_version_mismatch_short_circuits_before_building_live_ir(self, monkeypatch):
        # The live IR is never built: derive_domain is not called at all.
        def _fail(*args, **kwargs):
            raise AssertionError("derive_domain must not be called on mismatch")

        monkeypatch.setattr("protean.ir.staleness.derive_domain", _fail)
        _write_ir(
            self._protean_dir,
            {"ir_version": "0.0.9", "checksum": "sha256:whatever"},
        )

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.VERSION_MISMATCH
        assert result.domain_checksum is None

    def test_non_string_version_coerced_to_str(self):
        # A corrupt baseline with a non-string ir_version still yields a
        # str stored_version, honouring the StalenessResult field contract.
        _write_ir(
            self._protean_dir,
            {"ir_version": 0.1, "checksum": "sha256:whatever"},
        )

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.VERSION_MISMATCH
        assert result.stored_version == "0.1"
        assert isinstance(result.stored_version, str)

    def test_same_version_matching_checksum_is_fresh(self):
        # Negative #1: matching version + matching checksum → FRESH, not mismatch.
        live_ir = _live_ir_for_test7()
        assert live_ir["ir_version"] == SCHEMA_VERSION
        _write_ir(self._protean_dir, live_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.FRESH

    def test_same_version_differing_checksum_is_stale(self):
        # Negative #1: matching version but stale content → STALE, not mismatch.
        _write_ir(
            self._protean_dir,
            {"ir_version": SCHEMA_VERSION, "checksum": "sha256:outdated"},
        )

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.STALE

    def test_absent_version_falls_through_to_checksum(self):
        # Negative #2: a bare baseline with no ir_version keeps legacy behavior
        # (checksum comparison → STALE), never VERSION_MISMATCH.
        _write_ir(self._protean_dir, {"checksum": "sha256:outdated"})

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.STALE

    def test_disabled_gate_wins_over_version_mismatch(self):
        # Negative #3: staleness disabled → FRESH even when versions differ.
        _write_ir(
            self._protean_dir,
            {"ir_version": "0.0.9", "checksum": "sha256:whatever"},
        )

        result = check_staleness(
            "publishing7.py",
            self._protean_dir,
            config=CompatConfig(staleness_enabled=False),
        )

        assert result.status == StalenessStatus.FRESH


# ---------------------------------------------------------------------------
# TestCheckCLIText — `protean ir check` text output
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckCLIText:
    """CLI `protean ir check` command — text format."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def _write_live_ir(self) -> dict:
        live_ir = _live_ir_for_test7()
        _write_ir(self._protean_dir, live_ir)
        return live_ir

    def test_fresh_output_says_fresh(self):
        self._write_live_ir()
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert "fresh" in result.output.lower()

    def test_stale_output_says_stale(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert "stale" in result.output.lower()

    def test_no_ir_output_says_no_ir(self):
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert (
            "no materialized ir" in result.output.lower()
            or "not found" in result.output.lower()
        )

    def test_stale_output_shows_update_hint(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert "protean ir show" in result.output

    def test_stale_output_shows_checksums(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:old" + "0" * 58})
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert "stored" in result.output.lower() or "current" in result.output.lower()

    def test_version_mismatch_output_names_both_versions(self):
        _write_ir(
            self._protean_dir,
            {"ir_version": "0.0.9", "checksum": "sha256:whatever"},
        )
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert "version mismatch" in result.output.lower()
        assert "0.0.9" in result.output
        assert SCHEMA_VERSION in result.output

    def test_malformed_version_markup_does_not_crash(self):
        # A stored ir_version carrying rich-markup syntax must not raise
        # MarkupError from _print_check_text — it is escaped and exits 3.
        _write_ir(
            self._protean_dir,
            {"ir_version": "[/bold]", "checksum": "sha256:whatever"},
        )
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        # A clean typer.Exit surfaces as SystemExit; a MarkupError (the bug)
        # would surface as a MarkupError with exit_code 1.
        assert result.exit_code == 3
        assert isinstance(result.exception, SystemExit)
        assert "version mismatch" in result.output.lower()


# ---------------------------------------------------------------------------
# TestCheckCLIJSON — `protean ir check --format json`
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckCLIJSON:
    """CLI `protean ir check --format json` command."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def _write_live_ir(self) -> dict:
        live_ir = _live_ir_for_test7()
        _write_ir(self._protean_dir, live_ir)
        return live_ir

    def test_json_output_is_valid_json(self):
        self._write_live_ir()
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert isinstance(parsed, dict)

    def test_json_fresh_has_correct_status(self):
        self._write_live_ir()
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert parsed["status"] == "fresh"

    def test_json_stale_has_correct_status(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert parsed["status"] == "stale"

    def test_json_no_ir_has_correct_status(self):
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert parsed["status"] == "no_ir"

    def test_json_has_required_keys(self):
        self._write_live_ir()
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert "status" in parsed
        assert "domain_checksum" in parsed
        assert "stored_checksum" in parsed
        assert "ir_file" in parsed

    def test_json_fresh_checksums_match(self):
        live_ir = self._write_live_ir()
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert parsed["domain_checksum"] == live_ir["checksum"]
        assert parsed["stored_checksum"] == live_ir["checksum"]

    def test_json_no_ir_has_null_checksums(self):
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert parsed["domain_checksum"] is None
        assert parsed["stored_checksum"] is None
        assert parsed["ir_file"] is None

    def test_json_version_mismatch_has_status_and_versions(self):
        _write_ir(
            self._protean_dir,
            {"ir_version": "0.0.9", "checksum": "sha256:whatever"},
        )
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert parsed["status"] == "version_mismatch"
        assert parsed["stored_version"] == "0.0.9"
        assert parsed["current_version"] == SCHEMA_VERSION

    def test_json_fresh_has_null_versions(self):
        # stored_version/current_version are only populated on a mismatch.
        self._write_live_ir()
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "-f",
                "json",
            ],
        )
        parsed = json.loads(result.output)
        assert parsed["stored_version"] is None
        assert parsed["current_version"] is None


# ---------------------------------------------------------------------------
# TestCheckCLIExitCodes — exit code contract
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckCLIExitCodes:
    """CLI `protean ir check` exits with the correct code."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exit_0_when_fresh(self):
        from protean.ir.builder import IRBuilder
        from protean.utils.domain_discovery import derive_domain

        domain = derive_domain("publishing7.py")
        domain.init(traverse=False)
        live_ir = IRBuilder(domain).build()
        _write_ir(self._protean_dir, live_ir)

        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert result.exit_code == 0

    def test_exit_1_when_stale(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert result.exit_code == 1

    def test_exit_2_when_no_ir(self):
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert result.exit_code == 2

    def test_exit_3_on_version_mismatch(self):
        _write_ir(
            self._protean_dir,
            {"ir_version": "0.0.9", "checksum": "sha256:whatever"},
        )
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        assert result.exit_code == 3

    def test_exit_2_on_invalid_domain(self, tmp_path):
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "nonexistent_domain.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code == 2

    def test_exit_2_when_domain_load_fails_after_ir_found(self):
        # Write a valid ir.json so check_staleness proceeds past the NO_IR path,
        # then fails when trying to load the invalid domain module.
        _write_ir(self._protean_dir, {"checksum": "sha256:abc"})
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "nonexistent_domain.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code == 2

    def test_exit_2_when_load_stored_ir_raises(self):
        # Make ir.json a directory to trigger OSError → ValueError from load_stored_ir,
        # which propagates up through check_staleness and is caught by the generic handler.
        ir_as_dir = self._protean_dir / "ir.json"
        self._protean_dir.mkdir(parents=True, exist_ok=True)
        ir_as_dir.mkdir()
        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        )
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# TestPrintCheckTextBranches — direct unit tests for _print_check_text()
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestPrintCheckTextBranches:
    """Cover the None-checksum and None-ir_file branches in _print_check_text."""

    def test_fresh_with_none_checksum(self, capsys):
        from protean.cli.ir import _print_check_text
        from protean.ir.staleness import StalenessResult, StalenessStatus

        result = StalenessResult(
            status=StalenessStatus.FRESH,
            domain_checksum=None,
            stored_checksum=None,
            ir_file=None,
        )
        # Should not raise; just prints "IR is fresh." without the checksum line
        _print_check_text(result)

    def test_stale_with_none_stored_checksum(self):
        from protean.cli.ir import _print_check_text
        from protean.ir.staleness import StalenessResult, StalenessStatus

        result = StalenessResult(
            status=StalenessStatus.STALE,
            domain_checksum=None,
            stored_checksum=None,
            ir_file=None,
        )
        # All None — should not raise; prints stale message and hint
        _print_check_text(result)

    def test_no_ir_with_no_ir_file_uses_protean_dir(self, capsys):
        from protean.cli.ir import _print_check_text
        from protean.ir.staleness import StalenessResult, StalenessStatus

        result = StalenessResult(
            status=StalenessStatus.NO_IR,
            domain_checksum=None,
            stored_checksum=None,
            ir_file=None,
        )
        _print_check_text(result, protean_dir="/my/.protean")

        captured = capsys.readouterr()
        assert "/my/.protean" in captured.out

    def test_version_mismatch_with_none_ir_file(self, capsys):
        from protean.cli.ir import _print_check_text
        from protean.ir.staleness import StalenessResult, StalenessStatus

        result = StalenessResult(
            status=StalenessStatus.VERSION_MISMATCH,
            domain_checksum=None,
            stored_checksum="sha256:whatever",
            ir_file=None,
            stored_version="0.0.9",
            current_version="0.1.0",
        )
        # None ir_file must not raise; both versions appear in the message.
        _print_check_text(result)

        captured = capsys.readouterr()
        assert "0.0.9" in captured.out
        assert "0.1.0" in captured.out
