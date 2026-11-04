"""Tests for IR staleness detection — src/protean/ir/staleness.py and `protean ir check` CLI."""

import json
import os
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.ir import SCHEMA_URL, SCHEMA_VERSION
from protean.ir.builder import IRBuilder
from protean.ir.config import CompatConfig
from protean.ir.staleness import (
    StalenessResult,
    StalenessStatus,
    check_staleness,
    load_stored_ir,
    staleness_diagnostic,
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

    @pytest.mark.parametrize("subdir", ["", "nonexistent"])
    def test_returns_none_without_an_ir_file(self, tmp_path, subdir):
        # An empty directory and a missing directory both hold no ir.json.
        assert load_stored_ir(tmp_path / subdir) is None

    @pytest.mark.parametrize("as_str", [False, True])
    def test_returns_ir_dict_and_path_for_valid_file(self, tmp_path, as_str):
        ir = {"ir_version": "0.1.0", "checksum": "sha256:abc123", "clusters": {}}
        _write_ir(tmp_path, ir)

        result = load_stored_ir(str(tmp_path) if as_str else tmp_path)

        assert result is not None
        ir_dict, ir_path = result
        assert ir_dict == ir
        assert ir_path == tmp_path / "ir.json"

    def test_raises_for_invalid_json(self, tmp_path):
        bad = tmp_path / "ir.json"
        bad.write_text("{ not valid json", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid JSON"):
            load_stored_ir(tmp_path)

    @pytest.mark.parametrize("content", ["[]", "null", "5"])
    def test_raises_for_json_that_is_not_an_object(self, tmp_path, content):
        (tmp_path / "ir.json").write_text(content, encoding="utf-8")

        with pytest.raises(ValueError, match="is not a JSON object"):
            load_stored_ir(tmp_path)

    @pytest.mark.parametrize("kind", ["bytes_not_utf8", "directory"])
    def test_raises_for_a_file_that_cannot_be_read(self, tmp_path, kind):
        # An ir.json that is a directory makes read_text raise
        # IsADirectoryError, an OSError.
        if kind == "directory":
            (tmp_path / "ir.json").mkdir()
        else:
            (tmp_path / "ir.json").write_bytes(b"\xff\xfe")

        with pytest.raises(ValueError, match=r"Could not read .*ir\.json"):
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
        assert live_ir["ir_version"] == SCHEMA_VERSION
        _write_ir(self._protean_dir, live_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.FRESH
        assert result.domain_checksum == live_ir["checksum"]
        assert result.stored_checksum == live_ir["checksum"]
        assert result.ir_file is not None
        assert result.ir_file.name == "ir.json"

    def test_fresh_when_baseline_has_old_schema_url(self):
        """Baselines written before the IR's ``$schema`` URL moved to the docs
        site still name ``protean.dev``. The URL alone does not make them stale."""
        live_ir = _live_ir_for_test7()
        assert live_ir["$schema"] == SCHEMA_URL
        live_ir["$schema"] = f"https://protean.dev/ir/v{SCHEMA_VERSION}/schema.json"
        # Recompute as an older release would have, so the test fails if
        # ``$schema`` ever counts toward the checksum.
        live_ir["checksum"] = IRBuilder._compute_checksum(live_ir)
        _write_ir(self._protean_dir, live_ir)

        result = runner.invoke(
            app,
            [
                "ir",
                "check",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "fresh"

    def test_raises_when_no_domain_is_found(self, tmp_path, monkeypatch):
        """A stored IR present but no derivable domain must raise, not crash.

        With no domain path, no PROTEAN_DOMAIN and no domain.py in the
        working directory, discovery finds no domain (derive_domain is typed
        Domain | None), and check_staleness must not call .init() on None.
        """
        from protean.exceptions import NoDomainException

        _write_ir(self._protean_dir, _live_ir_for_test7())
        empty = tmp_path / "no_domain_here"
        empty.mkdir()
        # The class fixture restores the working directory. monkeypatch.chdir
        # would undo after that fixture and leave the process in test7.
        os.chdir(empty)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
        # Another test may have imported a module named ``domain``.
        monkeypatch.delitem(sys.modules, "domain", raising=False)

        with pytest.raises(NoDomainException, match="Could not derive"):
            check_staleness("", self._protean_dir)


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
        ``check_staleness`` considers it fresh with the same checksums."""
        from protean.cli._ir_utils import load_domain_ir

        show_ir = load_domain_ir("publishing7.py")
        _write_ir(self._protean_dir, show_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.FRESH
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
        # The baseline has no ir_version, so the legacy checksum comparison
        # decides, never VERSION_MISMATCH.
        stale_ir = {"checksum": "sha256:outdated000000000000000000000000"}
        _write_ir(self._protean_dir, stale_ir)

        result = check_staleness("publishing7.py", self._protean_dir)

        assert result.status == StalenessStatus.STALE
        assert result.domain_checksum != result.stored_checksum
        assert result.stored_checksum == "sha256:outdated000000000000000000000000"
        assert result.domain_checksum is not None
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

    @pytest.mark.parametrize("as_str", [False, True])
    def test_no_ir_without_loading_the_domain(self, as_str):
        # The domain module does not exist, so loading it would raise.
        protean_dir = str(self._empty_dir) if as_str else self._empty_dir

        result = check_staleness("no_such_staleness_domain.py", protean_dir)

        assert result.status == StalenessStatus.NO_IR
        assert result.domain_checksum is None
        assert result.stored_checksum is None
        assert result.ir_file is None


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

    @pytest.mark.parametrize("stored_version", ["0.0.9", "9.9.9"])
    def test_version_mismatch_without_loading_the_domain(self, stored_version):
        # Any version difference, older or newer, is a mismatch regardless of
        # checksum. The domain module does not exist, so building the live IR
        # would raise.
        _write_ir(
            self._protean_dir,
            {"ir_version": stored_version, "checksum": "sha256:whatever"},
        )

        result = check_staleness("no_such_staleness_domain.py", self._protean_dir)

        assert result.status == StalenessStatus.VERSION_MISMATCH
        assert result.stored_version == stored_version
        assert result.current_version == SCHEMA_VERSION
        assert result.stored_checksum == "sha256:whatever"
        assert result.domain_checksum is None
        assert result.ir_file is not None

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

    def test_same_version_differing_checksum_is_stale(self):
        # Negative #1: matching version but stale content → STALE, not mismatch.
        _write_ir(
            self._protean_dir,
            {"ir_version": SCHEMA_VERSION, "checksum": "sha256:outdated"},
        )

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

    def _check(self):
        return runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )

    def test_fresh_exits_0_and_says_fresh(self):
        self._write_live_ir()
        result = self._check()
        assert result.exit_code == 0
        assert "IR is fresh." in result.output

    def test_stale_exits_1_and_shows_checksums_and_update_hint(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:old" + "0" * 58})
        result = self._check()
        assert result.exit_code == 1
        assert "IR is stale" in result.output
        assert "stored:  sha256:old000000" in result.output
        assert "current: sha256:" in result.output
        assert "protean ir show" in result.output

    def test_no_ir_exits_2_and_says_no_ir(self):
        result = self._check()
        assert result.exit_code == 2
        assert "no materialized ir" in result.output.lower()

    def test_version_mismatch_exits_3_and_names_both_versions(self):
        _write_ir(
            self._protean_dir,
            {"ir_version": "0.0.9", "checksum": "sha256:whatever"},
        )
        result = self._check()
        assert result.exit_code == 3
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

    def test_malformed_stale_checksum_markup_does_not_crash(self):
        # A stored checksum carrying rich-markup syntax must not raise
        # MarkupError from the STALE branch of _print_check_text — it is
        # escaped and exits 1.
        _write_ir(
            self._protean_dir,
            {"ir_version": SCHEMA_VERSION, "checksum": "[/bold]sha256:outdated"},
        )
        result = runner.invoke(
            app,
            ["ir", "check", "-d", "publishing7.py", "--dir", str(self._protean_dir)],
        )
        # STALE also exits 1, so exit_code alone can't distinguish the bug —
        # check that the exception is a clean typer.Exit (SystemExit), not an
        # uncaught MarkupError.
        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "stale" in result.output.lower()


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

    def _check_json(self) -> dict:
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
        return parsed

    def test_json_fresh_has_status_checksums_and_null_versions(self):
        live_ir = self._write_live_ir()
        parsed = self._check_json()
        assert parsed["status"] == "fresh"
        assert parsed["domain_checksum"] == live_ir["checksum"]
        assert parsed["stored_checksum"] == live_ir["checksum"]
        assert "ir_file" in parsed
        # stored_version/current_version are only populated on a mismatch.
        assert parsed["stored_version"] is None
        assert parsed["current_version"] is None

    def test_json_stale_has_correct_status(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})
        assert self._check_json()["status"] == "stale"

    def test_json_no_ir_has_status_and_null_checksums(self):
        parsed = self._check_json()
        assert parsed["status"] == "no_ir"
        assert parsed["domain_checksum"] is None
        assert parsed["stored_checksum"] is None
        assert parsed["ir_file"] is None

    def test_json_version_mismatch_has_status_and_versions(self):
        _write_ir(
            self._protean_dir,
            {"ir_version": "0.0.9", "checksum": "sha256:whatever"},
        )
        parsed = self._check_json()
        assert parsed["status"] == "version_mismatch"
        assert parsed["stored_version"] == "0.0.9"
        assert parsed["current_version"] == SCHEMA_VERSION


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
# TestPrintCheckTextWithoutChecksumOrFile
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestPrintCheckTextWithoutChecksumOrFile:
    """The `protean ir check` text output leaves out the checksum and file lines
    when the result has no checksum or IR file."""

    def test_fresh_with_none_checksum(self, capsys):
        from protean.cli.ir import _print_check_text
        from protean.ir.staleness import StalenessResult, StalenessStatus

        result = StalenessResult(
            status=StalenessStatus.FRESH,
            domain_checksum=None,
            stored_checksum=None,
            ir_file=None,
        )
        _print_check_text(result)

        captured = capsys.readouterr()
        assert "IR is fresh." in captured.out
        assert "checksum:" not in captured.out

    def test_stale_with_none_stored_checksum(self, capsys):
        from protean.cli.ir import _print_check_text
        from protean.ir.staleness import StalenessResult, StalenessStatus

        result = StalenessResult(
            status=StalenessStatus.STALE,
            domain_checksum=None,
            stored_checksum=None,
            ir_file=None,
        )
        _print_check_text(result)

        captured = capsys.readouterr()
        assert "IR is stale" in captured.out
        assert "stored:" not in captured.out
        assert "current:" not in captured.out
        assert "file:" not in captured.out
        assert "to update." in captured.out

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


# ---------------------------------------------------------------------------
# TestStalenessDiagnostic
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestStalenessDiagnostic:
    """staleness_diagnostic() surfaces the IR_STALE coded diagnostic with its
    resolving operation, and the named command clears it end to end."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def _write_stale_ir(self) -> None:
        _write_ir(self._protean_dir, {"checksum": "sha256:outdated0000000000000000"})

    def test_non_stale_statuses_have_no_diagnostic(self):
        # Negative: IR_STALE is scoped to STALE only. Iterate every other status
        # so a status added later is covered automatically (NO_IR and
        # VERSION_MISMATCH are distinct outcomes and must not surface IR_STALE).
        non_stale = [s for s in StalenessStatus if s != StalenessStatus.STALE]
        assert non_stale
        for status in non_stale:
            result = StalenessResult(
                status=status,
                domain_checksum=None,
                stored_checksum=None,
                ir_file=None,
            )
            assert (
                staleness_diagnostic(result, domain_module="publishing7.py") is None
            ), status

    def test_stale_result_carries_ir_stale_and_resolving_operation(self):
        self._write_stale_ir()

        result = check_staleness("publishing7.py", self._protean_dir)
        assert result.status == StalenessStatus.STALE

        diag = staleness_diagnostic(result, domain_module="publishing7.py")
        assert diag is not None
        assert diag["code"] == "IR_STALE"
        assert diag["element"] == "publishing7.py"
        assert "publishing7.py" in diag["message"]
        assert diag["resolving_operation"] == {
            "command": "protean-check-staleness",
            "args": ["--fix"],
            "display": "protean-check-staleness --fix",
        }

    def test_dispatching_the_named_command_clears_the_diagnostic(self, monkeypatch):
        # End to end: emit → dispatch the resolving command the diagnostic names
        # → re-check → the diagnostic is gone.
        self._write_stale_ir()

        stale = check_staleness("publishing7.py", self._protean_dir)
        diag = staleness_diagnostic(stale, domain_module="publishing7.py")
        assert diag is not None
        op = diag["resolving_operation"]

        # Resolve the named command through the console-script table, so the
        # dispatched callable is whatever `op["command"]` actually maps to (not a
        # hook imported by name). A wrong command string fails the lookup here.
        scripts = {ep.name: ep for ep in entry_points(group="console_scripts")}
        assert op["command"] in scripts
        entry = scripts[op["command"]].load()

        # The staleness hook stages the regenerated file with `git add`. Point
        # git at a repository around the tmp baseline, so the staging runs for
        # real without touching the repository the tests run in.
        work_tree = self._protean_dir.parent
        subprocess.run(["git", "init", str(work_tree)], capture_output=True, check=True)
        monkeypatch.setenv("GIT_DIR", str(work_tree / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(work_tree))
        # Dispatch exactly what the diagnostic names (`protean-check-staleness
        # --fix`), plus the --domain/--dir context an agent supplies.
        argv = [
            op["command"],
            *op["args"],
            "--domain",
            "publishing7.py",
            "--dir",
            str(self._protean_dir),
        ]
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exc:
            entry()
        assert exc.value.code == 0

        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert staged == [".protean/ir.json"]

        after = check_staleness("publishing7.py", self._protean_dir)
        assert after.status == StalenessStatus.FRESH
        assert staleness_diagnostic(after, domain_module="publishing7.py") is None
