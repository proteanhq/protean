"""Tests for protean.ir.git — loading IR files from git commits."""

import json
import os
import subprocess

import pytest

from protean.ir.git import GitError, load_ir_from_commit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GIT_ENV_KEYS = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


def _git_env(tmp_path: str) -> dict[str, str]:
    """Build a minimal env dict for git commands in test repos."""
    env = dict(os.environ)
    env.update(_GIT_ENV_KEYS)
    env["HOME"] = str(tmp_path)
    return env


def _init_repo(tmp_path) -> dict[str, str]:
    """Initialise a git repo in tmp_path and return the env dict."""
    env = _git_env(str(tmp_path))
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    return env


def _commit_ir(tmp_path, ir_dict: dict, env: dict[str, str], msg: str = "ir") -> str:
    """Write ir_dict to .protean/ir.json, commit, and return the SHA."""
    ir_dir = tmp_path / ".protean"
    ir_dir.mkdir(exist_ok=True)
    (ir_dir / "ir.json").write_text(json.dumps(ir_dict), encoding="utf-8")
    subprocess.run(
        ["git", "add", ".protean/ir.json"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=tmp_path,
        capture_output=True,
        check=True,
        env=env,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()


@pytest.mark.no_test_domain
class TestLoadIrFromCommit:
    """Unit tests for load_ir_from_commit()."""

    @pytest.fixture(autouse=True)
    def _chdir(self, tmp_path, monkeypatch):
        """All tests run from inside the tmp_path git repo."""
        monkeypatch.chdir(tmp_path)
        self.tmp_path = tmp_path

    def test_loads_ir_from_head(self):
        ir_dict = {"ir_version": "0.1.0", "checksum": "sha256:abc123", "clusters": {}}
        env = _init_repo(self.tmp_path)
        _commit_ir(self.tmp_path, ir_dict, env)

        result = load_ir_from_commit("HEAD")
        assert result == ir_dict

    def test_loads_ir_from_specific_commit(self):
        ir_v1 = {"ir_version": "0.1.0", "checksum": "sha256:v1"}
        ir_v2 = {"ir_version": "0.1.0", "checksum": "sha256:v2"}

        env = _init_repo(self.tmp_path)
        v1_sha = _commit_ir(self.tmp_path, ir_v1, env, msg="v1")
        _commit_ir(self.tmp_path, ir_v2, env, msg="v2")

        result = load_ir_from_commit(v1_sha)
        assert result["checksum"] == "sha256:v1"

    def test_raises_git_error_for_nonexistent_commit(self):
        _init_repo(self.tmp_path)

        with pytest.raises(GitError, match="Failed to load"):
            load_ir_from_commit("nonexistent_ref")

    def test_raises_git_error_for_missing_file_at_commit(self):
        env = _init_repo(self.tmp_path)
        (self.tmp_path / "dummy.txt").write_text("hello")
        subprocess.run(
            ["git", "add", "."],
            cwd=self.tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=self.tmp_path,
            capture_output=True,
            check=True,
            env=env,
        )

        with pytest.raises(GitError, match="Failed to load"):
            load_ir_from_commit("HEAD")

    def test_raises_git_error_for_invalid_json(self):
        env = _init_repo(self.tmp_path)
        ir_dir = self.tmp_path / ".protean"
        ir_dir.mkdir()
        (ir_dir / "ir.json").write_text("{ not valid json }", encoding="utf-8")
        subprocess.run(
            ["git", "add", "."],
            cwd=self.tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "bad json"],
            cwd=self.tmp_path,
            capture_output=True,
            check=True,
            env=env,
        )

        with pytest.raises(GitError, match="Invalid JSON"):
            load_ir_from_commit("HEAD")

    def test_raises_git_error_when_not_a_repo(self, tmp_path, monkeypatch):
        # Use a separate fresh directory that is NOT a git repo
        empty = tmp_path / "norepo"
        empty.mkdir()
        monkeypatch.chdir(empty)
        with pytest.raises(GitError, match="Failed to load"):
            load_ir_from_commit("HEAD")

    def test_raises_git_error_when_git_not_found(self, monkeypatch):
        import protean.ir.git as git_mod

        def fake_run(*args, **kwargs):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(git_mod.subprocess, "run", fake_run)
        with pytest.raises(GitError, match="git is not installed"):
            load_ir_from_commit("HEAD")

    def test_default_path_is_protean_ir_json(self):
        import inspect

        sig = inspect.signature(load_ir_from_commit)
        assert sig.parameters["path"].default == ".protean/ir.json"

    def test_custom_path(self):
        """Can load IR from a non-default path."""
        env = _init_repo(self.tmp_path)
        ir_dict = {"checksum": "sha256:custom"}
        custom_dir = self.tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "ir.json").write_text(json.dumps(ir_dict), encoding="utf-8")
        subprocess.run(
            ["git", "add", "."],
            cwd=self.tmp_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "custom"],
            cwd=self.tmp_path,
            capture_output=True,
            check=True,
            env=env,
        )

        result = load_ir_from_commit("HEAD", "custom/ir.json")
        assert result["checksum"] == "sha256:custom"


@pytest.mark.no_test_domain
class TestGitErrorException:
    """Tests for the GitError exception class."""

    def test_git_error_is_exception(self):
        assert issubclass(GitError, Exception)

    def test_git_error_message(self):
        exc = GitError("something went wrong")
        assert str(exc) == "something went wrong"
