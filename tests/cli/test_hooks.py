"""Tests for pre-commit hook entry points — src/protean/cli/hooks.py."""

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
    _load_live_ir,
    check_compat_hook,
    check_staleness_hook,
)
from tests.shared import change_working_directory_to


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

    def test_requires_domain(self):
        parser = _build_staleness_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

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
        args = parser.parse_args(["--domain", "my_app"])
        assert args.dir == ".protean"

    def test_custom_dir(self):
        parser = _build_staleness_parser()
        args = parser.parse_args(["--domain", "my_app", "--dir", "/tmp/custom"])
        assert args.dir == "/tmp/custom"


# ---------------------------------------------------------------------------
# TestBuildCompatParser
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestBuildCompatParser:
    """Verify the compat argument parser."""

    def test_requires_domain(self):
        parser = _build_compat_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_domain_short_flag(self):
        parser = _build_compat_parser()
        args = parser.parse_args(["-d", "my_app.domain"])
        assert args.domain == "my_app.domain"

    def test_default_base(self):
        parser = _build_compat_parser()
        args = parser.parse_args(["--domain", "my_app"])
        assert args.base == "HEAD"

    def test_custom_base(self):
        parser = _build_compat_parser()
        args = parser.parse_args(["--domain", "my_app", "--base", "main"])
        assert args.base == "main"

    def test_default_dir(self):
        parser = _build_compat_parser()
        args = parser.parse_args(["--domain", "my_app"])
        assert args.dir == ".protean"

    def test_custom_dir(self):
        parser = _build_compat_parser()
        args = parser.parse_args(["--domain", "my_app", "--dir", "custom"])
        assert args.dir == "custom"


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

        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
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

        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

    def test_prints_stale_message(self, capsys):
        _write_ir(self._protean_dir, {"checksum": "sha256:old" + "0" * 58})

        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
            with pytest.raises(SystemExit):
                check_staleness_hook()

        captured = capsys.readouterr()
        assert "stale" in captured.err.lower()

    def test_prints_checksums_when_available(self, capsys):
        _write_ir(self._protean_dir, {"checksum": "sha256:old" + "0" * 58})

        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
            with pytest.raises(SystemExit):
                check_staleness_hook()

        captured = capsys.readouterr()
        assert "stored" in captured.err.lower()
        assert "current" in captured.err.lower()

    def test_prints_update_hint(self, capsys):
        _write_ir(self._protean_dir, {"checksum": "sha256:old"})

        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
            with pytest.raises(SystemExit):
                check_staleness_hook()

        captured = capsys.readouterr()
        assert "protean ir show" in captured.err

    def test_stale_without_stored_checksum(self, capsys):
        """Stale result where stored IR has no checksum field — covers branch partial."""
        _write_ir(self._protean_dir, {"ir_version": "0.1.0"})

        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
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

        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
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
        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

    def test_prints_missing_ir_message(self, capsys):
        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
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
        with patch("sys.argv", ["protean-check-staleness", "-d", "nonexistent_domain.py", "--dir", str(self._protean_dir)]):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1

    def test_exits_1_on_no_domain_exception(self, capsys):
        """Valid ir.json + invalid domain — NoDomainException from check_staleness."""
        _write_ir(self._protean_dir, {"checksum": "sha256:abc"})

        with patch("sys.argv", ["protean-check-staleness", "-d", "nonexistent_domain.py", "--dir", str(self._protean_dir)]):
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

        with patch("sys.argv", ["protean-check-staleness", "-d", "publishing7.py", "--dir", str(self._protean_dir)]):
            with pytest.raises(SystemExit) as exc_info:
                check_staleness_hook()
            assert exc_info.value.code == 1


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
                        capture_output=True, check=True, env=env,
                        cwd=self._repo_root,
                    )
                subprocess.run(
                    ["git", "commit", "-m", "test: hook compat"],
                    capture_output=True, check=True, env=env,
                    cwd=self._repo_root,
                )
                return self_ctx

            def __exit__(self_ctx, *_):
                subprocess.run(
                    ["git", "reset", "HEAD~1"],
                    capture_output=True, check=True, env=env,
                    cwd=self._repo_root,
                )
                for f in files:
                    if f.exists():
                        f.unlink()
                subprocess.run(
                    ["git", "checkout", "--", "."],
                    capture_output=True, check=True, env=env,
                    cwd=self._repo_root,
                )

        return _Ctx()

    def test_exits_0_when_no_changes(self):
        """Identical IR → no changes → exit 0."""
        live_ir = _live_ir_for_test7()
        protean_dir = self._test7_dir / ".protean"
        protean_dir.mkdir(parents=True, exist_ok=True)
        ir_file = protean_dir / "ir.json"
        ir_file.write_text(json.dumps(live_ir, indent=2), encoding="utf-8")

        env = _git_env()
        rel_dir = self._rel_path(".protean")
        with self._commit_and_cleanup([ir_file], env):
            with patch("sys.argv", [
                "protean-check-compat", "-d", "publishing7.py",
                "--base", "HEAD", "--dir", rel_dir,
            ]):
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
                        capture_output=True, check=True, env=env,
                        cwd=self._repo_root,
                    )
                subprocess.run(
                    ["git", "commit", "-m", "test: hook compat breaking"],
                    capture_output=True, check=True, env=env,
                    cwd=self._repo_root,
                )
                return self_ctx

            def __exit__(self_ctx, *_):
                subprocess.run(
                    ["git", "reset", "HEAD~1"],
                    capture_output=True, check=True, env=env,
                    cwd=self._repo_root,
                )
                for f in files:
                    if f.exists():
                        f.unlink()
                subprocess.run(
                    ["git", "checkout", "--", "."],
                    capture_output=True, check=True, env=env,
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
        ir_file.write_text(json.dumps(baseline_ir, indent=2), encoding="utf-8")

        env = _git_env()
        rel_dir = self._rel_path(".protean")
        with self._commit_and_cleanup([ir_file], env):
            with patch("sys.argv", [
                "protean-check-compat", "-d", "publishing7.py",
                "--base", "HEAD", "--dir", rel_dir,
            ]):
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
        with patch("sys.argv", [
            "protean-check-compat", "-d", "publishing7.py",
            "--base", "nonexistent_commit_abc123",
        ]):
            with pytest.raises(SystemExit) as exc_info:
                check_compat_hook()
            assert exc_info.value.code == 1

    def test_exits_1_on_invalid_domain(self):
        """Invalid domain → exit 1 from _load_live_ir."""
        with patch("protean.ir.git.load_ir_from_commit", return_value={"checksum": "sha256:abc"}):
            with patch("sys.argv", [
                "protean-check-compat", "-d", "nonexistent_domain.py",
            ]):
                with pytest.raises(SystemExit) as exc_info:
                    check_compat_hook()
                assert exc_info.value.code == 1
