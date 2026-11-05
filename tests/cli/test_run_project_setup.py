"""Tests for the post-generation setup that ``protean new`` runs.

The setup shells out to ``uv``, ``git`` and ``pre-commit``. These tests replace
the ``subprocess``, ``shutil`` and ``os`` names inside ``protean.cli.new`` with
stand-ins, so no real tool runs and no global module is patched.
"""

import importlib
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from protean.cli import app
from tests.shared import isolated_filesystem

new_module = importlib.import_module("protean.cli.new")

UV_PATH = "/fake/bin/uv"


class _RecordingSubprocess:
    """Stand-in for the ``subprocess`` module that records each ``run`` call."""

    CalledProcessError = subprocess.CalledProcessError

    def __init__(self, fail_on: list[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def run(self, args: list[str], **kwargs: Any) -> None:
        self.calls.append(list(args))
        if self.fail_on is not None and list(args) == self.fail_on:
            raise subprocess.CalledProcessError(returncode=1, cmd=args)


class _OsWithName:
    """Stand-in for the ``os`` module that reports a different ``os.name``."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, attr: str) -> Any:
        return getattr(os, attr)


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> _RecordingSubprocess:
    fake = _RecordingSubprocess()
    monkeypatch.setattr(new_module, "subprocess", fake)
    return fake


@pytest.fixture
def uv_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(new_module, "shutil", SimpleNamespace(which=lambda _: UV_PATH))


def _make_pre_commit(project_dir: Path) -> None:
    pre_commit = project_dir / ".venv" / "bin" / "pre-commit"
    pre_commit.parent.mkdir(parents=True)
    pre_commit.write_text("", encoding="utf-8")


def _flat(text: str) -> str:
    # Rich wraps at the terminal width; join the lines before matching.
    return " ".join(text.split())


@pytest.mark.usefixtures("uv_found")
class TestRunProjectSetupCommands:
    def test_runs_uv_git_and_pre_commit_in_order(
        self, tmp_path: Path, fake_subprocess: _RecordingSubprocess
    ) -> None:
        _make_pre_commit(tmp_path)

        new_module.run_project_setup(str(tmp_path))

        assert fake_subprocess.calls == [
            [UV_PATH, "sync", "--all-extras", "--all-groups"],
            ["git", "init"],
            ["git", "add", "."],
            [os.path.join(".venv", "bin", "pre-commit"), "install"],
        ]

    def test_restores_the_working_directory(
        self, tmp_path: Path, fake_subprocess: _RecordingSubprocess
    ) -> None:
        before = os.getcwd()

        new_module.run_project_setup(str(tmp_path))

        assert os.getcwd() == before

    def test_skips_hook_install_when_pre_commit_is_missing(
        self,
        tmp_path: Path,
        fake_subprocess: _RecordingSubprocess,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        new_module.run_project_setup(str(tmp_path))

        assert "Pre-commit not found, skipping hook installation" in _flat(
            capsys.readouterr().out
        )
        assert fake_subprocess.calls == [
            [UV_PATH, "sync", "--all-extras", "--all-groups"],
            ["git", "init"],
            ["git", "add", "."],
        ]

    def test_reports_a_failed_command_and_restores_the_working_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        fake = _RecordingSubprocess(fail_on=["git", "init"])
        monkeypatch.setattr(new_module, "subprocess", fake)
        before = os.getcwd()

        new_module.run_project_setup(str(tmp_path))

        out = _flat(capsys.readouterr().out)
        assert "Setup encountered an error:" in out
        assert "You can complete the setup manually." in out
        assert "Project setup complete!" not in out
        # The failure stops the setup: no ``git add`` after the failed init.
        assert fake.calls == [
            [UV_PATH, "sync", "--all-extras", "--all-groups"],
            ["git", "init"],
        ]
        assert os.getcwd() == before


def test_stops_when_uv_is_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_subprocess: _RecordingSubprocess,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(new_module, "shutil", SimpleNamespace(which=lambda _: None))
    before = os.getcwd()

    new_module.run_project_setup(str(tmp_path))

    out = _flat(capsys.readouterr().out)
    assert "uv not found. Install it from https://docs.astral.sh/uv/" in out
    assert "Project setup complete!" not in out
    assert fake_subprocess.calls == []
    assert os.getcwd() == before


@pytest.mark.usefixtures("uv_found", "fake_subprocess")
class TestActivationCommand:
    @pytest.mark.parametrize(
        ("shell", "expected"),
        [
            ("/bin/bash", "source .venv/bin/activate"),
            ("/usr/bin/zsh", "source .venv/bin/activate"),
            ("/usr/bin/fish", "source .venv/bin/activate.fish"),
            ("/bin/csh", "source .venv/bin/activate.csh"),
            ("/bin/tcsh", "source .venv/bin/activate.csh"),
            ("", "source .venv/bin/activate"),
        ],
    )
    def test_matches_the_shell_on_posix(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        shell: str,
        expected: str,
    ) -> None:
        monkeypatch.setenv("SHELL", shell)
        monkeypatch.setattr(new_module, "os", _OsWithName("posix"))

        new_module.run_project_setup(str(tmp_path))

        out = _flat(capsys.readouterr().out)
        assert f"cd {tmp_path} {expected} Then you can start developing" in out

    def test_uses_the_scripts_folder_on_windows(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("SHELL", "/usr/bin/fish")
        monkeypatch.setattr(new_module, "os", _OsWithName("nt"))

        new_module.run_project_setup(str(tmp_path))

        out = _flat(capsys.readouterr().out)
        assert f"cd {tmp_path} .venv\\Scripts\\activate Then you can start" in out


def test_new_runs_setup_on_the_generated_project_without_skip_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(new_module, "run_project_setup", calls.append)

    with isolated_filesystem() as output_dir:
        result = CliRunner().invoke(
            app, ["new", "foobar", "-o", output_dir, "--defaults"]
        )

    assert result.exit_code == 0, result.output
    assert calls == [os.path.join(output_dir, "foobar")]


def test_new_skips_setup_with_skip_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(new_module, "run_project_setup", calls.append)

    with isolated_filesystem() as output_dir:
        result = CliRunner().invoke(
            app, ["new", "foobar", "-o", output_dir, "--defaults", "--skip-setup"]
        )

    assert result.exit_code == 0, result.output
    assert calls == []
