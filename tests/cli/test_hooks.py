"""Tests for pre-commit hook entry points — src/protean/cli/hooks.py."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from protean.cli.hooks import (
    _build_compat_parser,
    _build_staleness_parser,
    _check_compat_single,
    _check_staleness_single,
    _git_add,
    _load_live_ir,
    _regenerate_ir,
    _resolve_domains,
    check_compat_hook,
    check_staleness_hook,
)
from protean.ir.config import CompatConfig
from tests.shared import change_working_directory_to


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_ir(directory: Path, ir_dict: dict) -> Path:
    """Write *ir_dict* as ir.json into *directory* and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ir.json"
    path.write_text(json.dumps(ir_dict, indent=2) + "\n", encoding="utf-8")
    return path


def _write_config(directory: Path, toml_content: str) -> Path:
    """Write a config.toml into *directory* and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.toml"
    path.write_text(toml_content, encoding="utf-8")
    return path


def _live_ir_for_test7() -> dict:
    """Return the live IR dict for the test7 domain (publishing7.py)."""
    from protean.ir.builder import IRBuilder
    from protean.utils.domain_discovery import derive_domain

    domain = derive_domain("publishing7.py")
    domain.init(traverse=False)
    return IRBuilder(domain).build()


# ---------------------------------------------------------------------------
# TestBuildStalenessParser
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestBuildStalenessParser:
    """Verify the staleness argument parser."""

    def test_domain_is_optional(self):
        parser = _build_staleness_parser()
        args = parser.parse_args([])
        assert args.domain is None

    def test_domain_short_flag(self):
        parser = _build_staleness_parser()
        args = parser.parse_args(["-d", "my_app.domain"])
        assert args.domain == "my_app.domain"

    def test_domain_long_flag(self):
        parser = _build_staleness_parser()
        args = parser.parse_args(["--domain", "my_app.domain"])
        assert args.domain == "my_app.domain"

    def test_default_dir(self):
        parser = _build_staleness_parser()
        args = parser.parse_args([])
        assert args.dir == ".protean"

    def test_custom_dir(self):
        parser = _build_staleness_parser()
        args = parser.parse_args(["--dir", "/tmp/custom"])
        assert args.dir == "/tmp/custom"

    def test_fix_flag_default_false(self):
        parser = _build_staleness_parser()
        args = parser.parse_args([])
        assert args.fix is False

    def test_fix_flag_long(self):
        parser = _build_staleness_parser()
        args = parser.parse_args(["--fix"])
        assert args.fix is True

    def test_fix_flag_short(self):
        parser = _build_staleness_parser()
        args = parser.parse_args(["-f"])
        assert args.fix is True


# ---------------------------------------------------------------------------
# TestBuildCompatParser
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestBuildCompatParser:
    """Verify the compat argument parser."""

    def test_domain_is_optional(self):
        parser = _build_compat_parser()
        args = parser.parse_args([])
        assert args.domain is None

    def test_domain_short_flag(self):
        parser = _build_compat_parser()
        args = parser.parse_args(["-d", "my_app.domain"])
        assert args.domain == "my_app.domain"

    def test_default_base(self):
        parser = _build_compat_parser()
        args = parser.parse_args([])
        assert args.base == "HEAD"

    def test_custom_base(self):
        parser = _build_compat_parser()
        args = parser.parse_args(["--base", "main"])
        assert args.base == "main"

    def test_default_dir(self):
        parser = _build_compat_parser()
        args = parser.parse_args([])
        assert args.dir == ".protean"

    def test_custom_dir(self):
        parser = _build_compat_parser()
        args = parser.parse_args(["--dir", "custom"])
        assert args.dir == "custom"


# ---------------------------------------------------------------------------
# TestResolveDomains
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestResolveDomains:
    """Test the _resolve_domains helper."""

    def test_explicit_domain_arg(self):
        args = argparse.Namespace(domain="my_app.domain", dir=".protean")
        config = CompatConfig()
        result = _resolve_domains(args, config)
        assert result == [("my_app.domain", Path(".protean"))]

    def test_config_driven_domains(self):
        args = argparse.Namespace(domain=None, dir=".protean")
        config = CompatConfig(
            domains={"identity": "identity.domain", "catalog": "catalog.domain"}
        )
        result = _resolve_domains(args, config)
        assert result == [
            ("identity.domain", Path(".protean/identity")),
            ("catalog.domain", Path(".protean/catalog")),
        ]

    def test_explicit_domain_takes_precedence(self):
        """When --domain is given, config [domains] is ignored."""
        args = argparse.Namespace(domain="my_app.domain", dir=".protean")
        config = CompatConfig(domains={"identity": "identity.domain"})
        result = _resolve_domains(args, config)
        assert result == [("my_app.domain", Path(".protean"))]

    def test_exits_when_no_domain_and_no_config(self):
        args = argparse.Namespace(domain=None, dir=".protean")
        config = CompatConfig()
        with pytest.raises(SystemExit) as exc_info:
            _resolve_domains(args, config)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# TestLoadLiveIr
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestLoadLiveIr:
    """Test the _load_live_ir helper."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_returns_valid_ir(self):
        ir = _load_live_ir("publishing7.py")
        assert isinstance(ir, dict)
        assert "checksum" in ir

    def test_exits_on_invalid_domain(self):
        with pytest.raises(SystemExit) as exc_info:
            _load_live_ir("nonexistent_domain.py")
        assert exc_info.value.code == 1

    def test_exits_on_domain_init_error(self, monkeypatch):
        """If domain.init() raises, _load_live_ir should exit 1."""
        from protean.utils import domain_discovery

        class FakeDomain:
            def init(self):
                raise RuntimeError("init failed")

        monkeypatch.setattr(domain_discovery, "derive_domain", lambda _: FakeDomain())

        with pytest.raises(SystemExit) as exc_info:
            _load_live_ir("publishing7.py")
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# TestRegenerateIr
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestRegenerateIr:
    """Test the _regenerate_ir helper."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_writes_ir_json(self, tmp_path):
        protean_dir = tmp_path / ".protean"
        ir = _regenerate_ir("publishing7.py", protean_dir)
        ir_path = protean_dir / "ir.json"
        assert ir_path.exists()
        stored = json.loads(ir_path.read_text(encoding="utf-8"))
        assert stored["checksum"] == ir["checksum"]

    def test_creates_directory(self, tmp_path):
        protean_dir = tmp_path / "deep" / "nested" / ".protean"
        _regenerate_ir("publishing7.py", protean_dir)
        assert (protean_dir / "ir.json").exists()


# ---------------------------------------------------------------------------
# TestGitAdd
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestGitAdd:
    """Test the _git_add helper."""

    def test_stages_file(self, tmp_path):
        """_git_add runs without error on a real git-tracked file."""
        # This test runs in the protean repo, so we can stage a temp file
        # Just verify it doesn't crash — the actual staging is best-effort
        fake_path = tmp_path / "nonexistent.json"
        # Should not raise, even if file doesn't exist
        _git_add(fake_path)

    def test_handles_missing_git(self, monkeypatch):
        """_git_add prints a warning when git is not found."""
        monkeypatch.setattr(
            "protean.cli.hooks.subprocess.run",
            lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("no git")),
        )
        # Should not raise
        _git_add(Path("/fake/path.json"))

    def test_handles_git_error(self, monkeypatch):
        """_git_add prints a warning when git add fails."""

        def fake_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "git add")

        monkeypatch.setattr("protean.cli.hooks.subprocess.run", fake_run)
        # Should not raise
        _git_add(Path("/fake/path.json"))


# ---------------------------------------------------------------------------
# TestCheckStalenessHook — fresh
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckStalenessHookFresh:
    """check_staleness_hook() exits 0 when IR is fresh."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_0_when_fresh(self):
        live_ir = _live_ir_for_test7()
        _write_ir(self._protean_dir, live_ir)

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# TestCheckStalenessHook — stale
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckStalenessHookStale:
    """check_staleness_hook() exits 1 when IR is stale."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_1_when_stale(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

    def test_prints_stale_message(self, capsys):
        _write_ir(self._protean_dir, {"checksum": "sha256:old" + "0" * 58})

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit):
                check_staleness_hook()

        captured = capsys.readouterr()
        assert "stale" in captured.err.lower()

    def test_prints_checksums_when_available(self, capsys):
        _write_ir(self._protean_dir, {"checksum": "sha256:old" + "0" * 58})

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit):
                check_staleness_hook()

        captured = capsys.readouterr()
        assert "stored" in captured.err.lower()
        assert "current" in captured.err.lower()

    def test_prints_update_hint(self, capsys):
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit):
                check_staleness_hook()

        captured = capsys.readouterr()
        assert "protean ir show" in captured.err
        assert "--fix" in captured.err

    def test_stale_without_stored_checksum(self, capsys):
        """Stale result where stored IR has no checksum field — covers branch partial."""
        _write_ir(self._protean_dir, {"ir_version": "0.1.0"})

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "stale" in captured.err.lower()
        # stored_checksum is None, so "stored:" line should NOT appear
        assert "stored:" not in captured.err

    def test_prints_update_hint_uses_configured_dir(self, capsys):
        """The update hint uses the configured --dir, not hardcoded .protean."""
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit):
                check_staleness_hook()

        captured = capsys.readouterr()
        assert str(self._protean_dir) in captured.err


# ---------------------------------------------------------------------------
# TestCheckStalenessHook — no IR
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckStalenessHookNoIR:
    """check_staleness_hook() exits 1 when no IR exists."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_1_when_no_ir(self):
        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

    def test_prints_missing_ir_message(self, capsys):
        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit):
                check_staleness_hook()

        captured = capsys.readouterr()
        assert "no materialized ir" in captured.err.lower()


# ---------------------------------------------------------------------------
# TestCheckStalenessHook — error paths
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckStalenessHookErrors:
    """check_staleness_hook() handles domain loading errors."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_1_on_invalid_domain_without_ir(self):
        """No ir.json + invalid domain — NO_IR path (not NoDomainException)."""
        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "nonexistent_domain.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

    def test_exits_1_on_no_domain_exception(self, capsys):
        """Valid ir.json + invalid domain — NoDomainException from check_staleness."""
        _write_ir(self._protean_dir, {"checksum": "sha256:abc"})

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "nonexistent_domain.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "error" in captured.err.lower()

    def test_exits_1_on_generic_exception(self, capsys):
        """Trigger a generic exception in check_staleness (not NoDomainException)."""
        # Write ir.json as a directory to cause an OSError → ValueError
        self._protean_dir.mkdir(parents=True, exist_ok=True)
        (self._protean_dir / "ir.json").mkdir()

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

    def test_exits_1_on_invalid_config(self, capsys):
        """Invalid config.toml → exit 1 with error message."""
        _write_config(self._protean_dir, 'staleness = "not a table"')

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "invalid" in captured.err.lower()

    def test_exits_0_when_staleness_disabled(self):
        """staleness.enabled = false → exit 0 immediately."""
        _write_config(self._protean_dir, "[staleness]\nenabled = false\n")

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "-d",
                "publishing7.py",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 0

    def test_exits_1_when_no_domain_and_no_config(self):
        """No --domain and no [domains] → exit 1."""
        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# TestCheckStalenessHook — fix mode
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckStalenessHookFix:
    """check_staleness_hook() with --fix regenerates stale IR."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_fix_regenerates_stale_ir(self, capsys):
        """--fix regenerates stale IR and exits 0."""
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})

        with (
            patch(
                "sys.argv",
                [
                    "protean-check-staleness",
                    "-d",
                    "publishing7.py",
                    "--dir",
                    str(self._protean_dir),
                    "--fix",
                ],
            ),
            patch("protean.cli.hooks._git_add"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 0

        # Verify the IR file was regenerated
        ir_path = self._protean_dir / "ir.json"
        assert ir_path.exists()
        stored = json.loads(ir_path.read_text(encoding="utf-8"))
        assert stored["checksum"] != "sha256:old"

        captured = capsys.readouterr()
        assert "fixed" in captured.err.lower()

    def test_fix_generates_missing_ir(self, capsys):
        """--fix generates IR when none exists and exits 0."""
        with (
            patch(
                "sys.argv",
                [
                    "protean-check-staleness",
                    "-d",
                    "publishing7.py",
                    "--dir",
                    str(self._protean_dir),
                    "--fix",
                ],
            ),
            patch("protean.cli.hooks._git_add"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 0

        ir_path = self._protean_dir / "ir.json"
        assert ir_path.exists()

    def test_fix_stages_file_with_git_add(self):
        """--fix calls _git_add to stage the regenerated file."""
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})
        staged_paths: list[Path] = []

        def capture_git_add(path: Path) -> None:
            staged_paths.append(path)

        with (
            patch(
                "sys.argv",
                [
                    "protean-check-staleness",
                    "-d",
                    "publishing7.py",
                    "--dir",
                    str(self._protean_dir),
                    "--fix",
                ],
            ),
            patch("protean.cli.hooks._git_add", side_effect=capture_git_add),
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 0

        assert len(staged_paths) == 1
        assert staged_paths[0] == self._protean_dir / "ir.json"

    def test_fix_exits_1_on_regeneration_failure(self, capsys):
        """--fix exits 1 if IR regeneration fails."""
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})

        with (
            patch(
                "sys.argv",
                [
                    "protean-check-staleness",
                    "-d",
                    "publishing7.py",
                    "--dir",
                    str(self._protean_dir),
                    "--fix",
                ],
            ),
            patch(
                "protean.cli.hooks._regenerate_ir",
                side_effect=RuntimeError("build failed"),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "failed to regenerate" in captured.err.lower()

    def test_fix_skips_fresh_ir(self):
        """--fix does nothing when IR is already fresh."""
        live_ir = _live_ir_for_test7()
        _write_ir(self._protean_dir, live_ir)

        staged_paths: list[Path] = []

        with (
            patch(
                "sys.argv",
                [
                    "protean-check-staleness",
                    "-d",
                    "publishing7.py",
                    "--dir",
                    str(self._protean_dir),
                    "--fix",
                ],
            ),
            patch(
                "protean.cli.hooks._git_add",
                side_effect=lambda p: staged_paths.append(p),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 0

        # git add should NOT have been called — IR was fresh
        assert len(staged_paths) == 0


# ---------------------------------------------------------------------------
# TestCheckStalenessHook — multi-domain
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckStalenessHookMultiDomain:
    """check_staleness_hook() with [domains] config."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_checks_all_configured_domains(self, capsys):
        """Multi-domain: checks each domain in [domains] section."""
        live_ir = _live_ir_for_test7()

        # Write config with one domain
        _write_config(
            self._protean_dir,
            '[domains]\npublishing = "publishing7.py"\n',
        )
        # Write fresh IR for that domain
        _write_ir(self._protean_dir / "publishing", live_ir)

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 0

    def test_reports_all_stale_domains(self, capsys):
        """Multi-domain: reports staleness for each stale domain."""
        _write_config(
            self._protean_dir,
            '[domains]\npublishing = "publishing7.py"\n',
        )
        _write_ir(self._protean_dir / "publishing", {"checksum": "sha256:old"})

        with patch(
            "sys.argv",
            [
                "protean-check-staleness",
                "--dir",
                str(self._protean_dir),
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "publishing7.py" in captured.err

    def test_fix_with_multi_domain(self, capsys):
        """Multi-domain + --fix: regenerates all stale IRs."""
        _write_config(
            self._protean_dir,
            '[domains]\npublishing = "publishing7.py"\n',
        )
        _write_ir(self._protean_dir / "publishing", {"checksum": "sha256:old"})

        with (
            patch(
                "sys.argv",
                [
                    "protean-check-staleness",
                    "--dir",
                    str(self._protean_dir),
                    "--fix",
                ],
            ),
            patch("protean.cli.hooks._git_add"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 0

        ir_path = self._protean_dir / "publishing" / "ir.json"
        assert ir_path.exists()
        stored = json.loads(ir_path.read_text(encoding="utf-8"))
        assert stored["checksum"] != "sha256:old"


# ---------------------------------------------------------------------------
# TestCheckStalenesseSingle — unit tests for the inner function
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckStalenessSingle:
    """Unit tests for _check_staleness_single."""

    @pytest.fixture(autouse=True)
    def reset_path(self, tmp_path):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        self._protean_dir = tmp_path / ".protean"
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_returns_true_when_fresh(self):
        live_ir = _live_ir_for_test7()
        _write_ir(self._protean_dir, live_ir)
        config = CompatConfig()
        assert (
            _check_staleness_single(
                "publishing7.py", self._protean_dir, fix=False, config=config
            )
            is True
        )

    def test_returns_false_when_stale(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})
        config = CompatConfig()
        assert (
            _check_staleness_single(
                "publishing7.py", self._protean_dir, fix=False, config=config
            )
            is False
        )

    def test_returns_false_on_no_domain(self):
        _write_ir(self._protean_dir, {"checksum": "sha256:abc"})
        config = CompatConfig()
        assert (
            _check_staleness_single(
                "nonexistent_domain.py", self._protean_dir, fix=False, config=config
            )
            is False
        )

    def test_returns_false_on_generic_error(self):
        """Generic exception from check_staleness → returns False."""
        self._protean_dir.mkdir(parents=True, exist_ok=True)
        (self._protean_dir / "ir.json").mkdir()  # directory, not file
        config = CompatConfig()
        assert (
            _check_staleness_single(
                "publishing7.py", self._protean_dir, fix=False, config=config
            )
            is False
        )


# ---------------------------------------------------------------------------
# TestCheckCompatHook — git-based tests
# ---------------------------------------------------------------------------


_GIT_ENV_KEYS = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(_GIT_ENV_KEYS)
    return env


def _has_git_repo() -> bool:
    """Return True if we're inside a git repository with git available."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.mark.no_test_domain
@pytest.mark.skipif(not _has_git_repo(), reason="requires git and a .git directory")
class TestCheckCompatHookNoBreaking:
    """check_compat_hook() exits 0 when no breaking changes found."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._original_path = sys.path[:]
        self._cwd = Path.cwd()
        change_working_directory_to("test7")
        self._test7_dir = Path.cwd()
        self._repo_root = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], text=True
            ).strip()
        )
        yield
        sys.path[:] = self._original_path
        os.chdir(self._cwd)

    def _rel_path(self, *parts: str) -> str:
        abs_path = self._test7_dir.joinpath(*parts)
        return str(abs_path.relative_to(self._repo_root))

    def _commit_and_cleanup(self, files: list[Path], env: dict[str, str]):
        class _Ctx:
            def __enter__(self_ctx):
                for f in files:
                    subprocess.run(
                        ["git", "add", str(f)],
                        capture_output=True,
                        check=True,
                        env=env,
                        cwd=self._repo_root,
                    )
                subprocess.run(
                    ["git", "commit", "-m", "test: hook compat"],
                    capture_output=True,
                    check=True,
                    env=env,
                    cwd=self._repo_root,
                )
                return self_ctx

            def __exit__(self_ctx, *_):
                subprocess.run(
                    ["git", "reset", "HEAD~1"],
                    capture_output=True,
                    check=True,
                    env=env,
                    cwd=self._repo_root,
                )
                for f in files:
                    if f.exists():
                        f.unlink()
                    subprocess.run(
                        ["git", "checkout", "--", str(f)],
                        capture_output=True,
                        env=env,
                        cwd=self._repo_root,
                    )

        return _Ctx()

    def test_exits_0_when_no_changes(self):
        """Identical IR → no changes → exit 0."""
        live_ir = _live_ir_for_test7()
        protean_dir = self._test7_dir / ".protean"
        protean_dir.mkdir(parents=True, exist_ok=True)
        ir_file = protean_dir / "ir.json"
        ir_file.write_text(json.dumps(live_ir, indent=2) + "\n", encoding="utf-8")

        env = _git_env()
        rel_dir = self._rel_path(".protean")
        with self._commit_and_cleanup([ir_file], env):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "publishing7.py",
                    "--base",
                    "HEAD",
                    "--dir",
                    rel_dir,
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 0


@pytest.mark.no_test_domain
@pytest.mark.skipif(not _has_git_repo(), reason="requires git and a .git directory")
class TestCheckCompatHookBreaking:
    """check_compat_hook() exits 1 when breaking changes are found."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._original_path = sys.path[:]
        self._cwd = Path.cwd()
        change_working_directory_to("test7")
        self._test7_dir = Path.cwd()
        self._repo_root = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], text=True
            ).strip()
        )
        yield
        sys.path[:] = self._original_path
        os.chdir(self._cwd)

    def _rel_path(self, *parts: str) -> str:
        abs_path = self._test7_dir.joinpath(*parts)
        return str(abs_path.relative_to(self._repo_root))

    def _commit_and_cleanup(self, files: list[Path], env: dict[str, str]):
        class _Ctx:
            def __enter__(self_ctx):
                for f in files:
                    subprocess.run(
                        ["git", "add", str(f)],
                        capture_output=True,
                        check=True,
                        env=env,
                        cwd=self._repo_root,
                    )
                subprocess.run(
                    ["git", "commit", "-m", "test: hook compat breaking"],
                    capture_output=True,
                    check=True,
                    env=env,
                    cwd=self._repo_root,
                )
                return self_ctx

            def __exit__(self_ctx, *_):
                subprocess.run(
                    ["git", "reset", "HEAD~1"],
                    capture_output=True,
                    check=True,
                    env=env,
                    cwd=self._repo_root,
                )
                for f in files:
                    if f.exists():
                        f.unlink()
                    subprocess.run(
                        ["git", "checkout", "--", str(f)],
                        capture_output=True,
                        env=env,
                        cwd=self._repo_root,
                    )

        return _Ctx()

    def test_exits_1_when_breaking_changes(self, capsys):
        """Baseline has a field that's missing from live domain → breaking → exit 1."""
        live_ir = _live_ir_for_test7()

        # Add an extra required field to the baseline, so that the live domain
        # appears to have "removed" it → breaking change.
        baseline_ir = json.loads(json.dumps(live_ir))  # deep copy
        baseline_ir["checksum"] = "sha256:modified_baseline"
        for cluster_fqn, cluster in baseline_ir.get("clusters", {}).items():
            cluster["aggregate"]["fields"]["extra_required_field"] = {
                "type": "String",
                "required": True,
                "default": None,
                "unique": False,
                "identifier": False,
            }
            break  # only modify the first cluster

        protean_dir = self._test7_dir / ".protean"
        protean_dir.mkdir(parents=True, exist_ok=True)
        ir_file = protean_dir / "ir.json"
        ir_file.write_text(json.dumps(baseline_ir, indent=2) + "\n", encoding="utf-8")

        env = _git_env()
        rel_dir = self._rel_path(".protean")
        with self._commit_and_cleanup([ir_file], env):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "publishing7.py",
                    "--base",
                    "HEAD",
                    "--dir",
                    rel_dir,
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "breaking" in captured.err.lower()


# ---------------------------------------------------------------------------
# TestCheckCompatHook — error paths
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckCompatHookErrors:
    """check_compat_hook() error handling."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_exits_1_on_git_error(self):
        """GitError when loading baseline → exit 1."""
        with patch(
            "sys.argv",
            [
                "protean-check-compat",
                "-d",
                "publishing7.py",
                "--base",
                "nonexistent_commit_abc123",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_compat_hook()
            assert exc_info.value.code == 1

    def test_exits_1_on_invalid_domain(self):
        """Invalid domain → exit 1 from _load_live_ir."""
        with patch(
            "protean.ir.git.load_ir_from_commit",
            return_value={"checksum": "sha256:abc"},
        ):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "nonexistent_domain.py",
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 1

    def test_exits_0_on_non_breaking_changes(self):
        """Non-breaking changes only — exit 0."""
        live_ir = _live_ir_for_test7()

        # Make baseline missing an optional field → live domain "added" it → safe
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:stripped_baseline"
        for cluster_fqn, cluster in baseline_ir.get("clusters", {}).items():
            fields = cluster["aggregate"]["fields"]
            for field_name, field_info in list(fields.items()):
                if not field_info.get("identifier") and not field_info.get("required"):
                    del fields[field_name]
                    break
            break

        with patch("protean.ir.git.load_ir_from_commit", return_value=baseline_ir):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "publishing7.py",
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 0

    def test_exits_1_on_invalid_config(self, capsys):
        """Invalid config.toml → exit 1."""
        with patch(
            "protean.ir.config.load_config",
            side_effect=ValueError("bad config"),
        ):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "publishing7.py",
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "invalid" in captured.err.lower()

    def test_exits_0_when_strictness_off(self):
        """strictness=off → exit 0 immediately."""
        with patch(
            "protean.ir.config.load_config",
            return_value=CompatConfig(strictness="off"),
        ):
            with patch(
                "sys.argv",
                [
                    "protean-check-compat",
                    "-d",
                    "publishing7.py",
                ],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 0

    def test_exits_1_when_no_domain_and_no_config(self):
        """No --domain and no [domains] → exit 1."""
        with patch(
            "sys.argv",
            [
                "protean-check-compat",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                check_compat_hook()
            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# TestCheckCompatHook — multi-domain
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
@pytest.mark.skipif(not _has_git_repo(), reason="requires git and a .git directory")
class TestCheckCompatHookMultiDomain:
    """check_compat_hook() with [domains] config."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self._original_path = sys.path[:]
        self._cwd = Path.cwd()
        change_working_directory_to("test7")
        self._test7_dir = Path.cwd()
        self._repo_root = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], text=True
            ).strip()
        )
        yield
        sys.path[:] = self._original_path
        os.chdir(self._cwd)

    def _rel_path(self, *parts: str) -> str:
        abs_path = self._test7_dir.joinpath(*parts)
        return str(abs_path.relative_to(self._repo_root))

    def _commit_and_cleanup(self, files: list[Path], env: dict[str, str]):
        class _Ctx:
            def __enter__(self_ctx):
                for f in files:
                    subprocess.run(
                        ["git", "add", str(f)],
                        capture_output=True,
                        check=True,
                        env=env,
                        cwd=self._repo_root,
                    )
                subprocess.run(
                    ["git", "commit", "-m", "test: hook compat multi-domain"],
                    capture_output=True,
                    check=True,
                    env=env,
                    cwd=self._repo_root,
                )
                return self_ctx

            def __exit__(self_ctx, *_):
                subprocess.run(
                    ["git", "reset", "HEAD~1"],
                    capture_output=True,
                    check=True,
                    env=env,
                    cwd=self._repo_root,
                )
                for f in files:
                    if f.exists():
                        f.unlink()
                    subprocess.run(
                        ["git", "checkout", "--", str(f)],
                        capture_output=True,
                        env=env,
                        cwd=self._repo_root,
                    )

        return _Ctx()

    def test_multi_domain_checks_all(self):
        """Multi-domain compat: checks each domain in [domains]."""
        live_ir = _live_ir_for_test7()

        protean_dir = self._test7_dir / ".protean"

        # Write config.toml
        _write_config(protean_dir, '[domains]\npublishing = "publishing7.py"\n')

        # Write fresh IR for the domain subdirectory
        pub_dir = protean_dir / "publishing"
        pub_dir.mkdir(parents=True, exist_ok=True)
        ir_file = pub_dir / "ir.json"
        ir_file.write_text(json.dumps(live_ir, indent=2) + "\n", encoding="utf-8")

        env = _git_env()
        config_file = protean_dir / "config.toml"
        with self._commit_and_cleanup([ir_file, config_file], env):
            # For compat multi-domain, --dir is the base .protean dir.
            # git loads baseline from <dir>/<name>/ir.json using repo-relative paths.
            # We need the base dir relative to repo root for git, but config.toml
            # needs to be loadable from disk (CWD is test7 dir, so use absolute).
            # Mock load_config to return the config with domains, and use
            # repo-relative dir for git baseline loading.
            rel_dir = self._rel_path(".protean")
            with patch(
                "protean.ir.config.load_config",
                return_value=CompatConfig(
                    domains={"publishing": "publishing7.py"},
                ),
            ):
                with patch(
                    "sys.argv",
                    [
                        "protean-check-compat",
                        "--base",
                        "HEAD",
                        "--dir",
                        rel_dir,
                    ],
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        check_compat_hook()
                    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# TestCheckCompatSingle — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCheckCompatSingle:
    """Unit tests for _check_compat_single."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        change_working_directory_to("test7")
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_returns_false_on_git_error(self, capsys):
        config = CompatConfig()
        result = _check_compat_single(
            "publishing7.py",
            Path(".protean"),
            base="nonexistent_commit_abc123",
            config=config,
        )
        assert result is False
        captured = capsys.readouterr()
        assert "error" in captured.err.lower()

    def test_warn_mode_returns_true_for_breaking(self, capsys):
        """strictness=warn → report breaking changes but return True."""
        live_ir = _live_ir_for_test7()
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified"
        for cluster_fqn, cluster in baseline_ir.get("clusters", {}).items():
            cluster["aggregate"]["fields"]["extra_field"] = {
                "type": "String",
                "required": True,
                "default": None,
                "unique": False,
                "identifier": False,
            }
            break

        config = CompatConfig(strictness="warn")
        with patch("protean.ir.git.load_ir_from_commit", return_value=baseline_ir):
            result = _check_compat_single(
                "publishing7.py",
                Path(".protean"),
                base="HEAD",
                config=config,
            )
        assert result is True
        captured = capsys.readouterr()
        assert "warn" in captured.err.lower()

    def test_exclude_filters_breaking_changes(self):
        """config.exclude filters out breaking changes by FQN."""
        live_ir = _live_ir_for_test7()
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified"

        # Find the first cluster FQN to use as the exclude target
        first_fqn = next(iter(baseline_ir.get("clusters", {})))
        for cluster_fqn, cluster in baseline_ir.get("clusters", {}).items():
            cluster["aggregate"]["fields"]["excluded_field"] = {
                "type": "String",
                "required": True,
                "default": None,
                "unique": False,
                "identifier": False,
            }
            break

        config = CompatConfig(exclude=(first_fqn,))
        with patch("protean.ir.git.load_ir_from_commit", return_value=baseline_ir):
            result = _check_compat_single(
                "publishing7.py",
                Path(".protean"),
                base="HEAD",
                config=config,
            )
        # Breaking change excluded → should pass
        assert result is True

    def test_returns_true_on_non_breaking_changes(self):
        """Non-breaking changes only → returns True."""
        live_ir = _live_ir_for_test7()
        baseline_ir = json.loads(json.dumps(live_ir))
        baseline_ir["checksum"] = "sha256:modified"
        # Remove an optional field from baseline → "added" in live → non-breaking
        for cluster_fqn, cluster in baseline_ir.get("clusters", {}).items():
            fields = cluster["aggregate"]["fields"]
            for field_name, field_info in list(fields.items()):
                if not field_info.get("identifier") and not field_info.get("required"):
                    del fields[field_name]
                    break
            break

        config = CompatConfig()
        with patch("protean.ir.git.load_ir_from_commit", return_value=baseline_ir):
            result = _check_compat_single(
                "publishing7.py",
                Path(".protean"),
                base="HEAD",
                config=config,
            )
        assert result is True


# ---------------------------------------------------------------------------
# Config parsing tests for [domains]
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestConfigDomainsParsing:
    """Test [domains] section parsing in CompatConfig."""

    def test_empty_domains_by_default(self):
        config = CompatConfig()
        assert config.domains == {}

    def test_domains_from_dict(self):
        config = CompatConfig(domains={"identity": "identity.domain"})
        assert config.domains == {"identity": "identity.domain"}

    def test_invalid_domains_type(self):
        with pytest.raises(ValueError, match="domains must be a mapping"):
            CompatConfig(domains="not a dict")  # type: ignore[arg-type]

    def test_domains_from_config_file(self, tmp_path):
        from protean.ir.config import load_config

        _write_config(
            tmp_path,
            '[domains]\nidentity = "identity.domain"\ncatalog = "catalog.domain"\n',
        )
        config = load_config(tmp_path)
        assert config.domains == {
            "identity": "identity.domain",
            "catalog": "catalog.domain",
        }

    def test_invalid_domains_values(self, tmp_path):
        from protean.ir.config import load_config

        _write_config(tmp_path, "[domains]\nidentity = 42\n")
        with pytest.raises(ValueError, match="string key-value"):
            load_config(tmp_path)

    def test_invalid_domains_table_type(self, tmp_path):
        from protean.ir.config import load_config

        _write_config(tmp_path, 'domains = "not a table"\n')
        with pytest.raises(ValueError, match="domains must be a TOML table"):
            load_config(tmp_path)
