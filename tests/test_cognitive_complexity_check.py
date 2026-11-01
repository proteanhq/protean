"""complexipy fails a function over the cognitive complexity limit.

``[tool.complexipy]`` in ``pyproject.toml`` sets the limit and the paths, and
``complexipy-snapshot.json`` lists the functions that were over the limit when
the check arrived. CI and pre-commit run complexipy over those paths.

Each test runs complexipy in a temporary folder with a copy of the project's
config. A passing run rewrites the snapshot, so a run inside the repository
would change a tracked file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_test_domain

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "pyproject.toml"
SNAPSHOT = ROOT / "complexipy-snapshot.json"
CHECKED_PATHS = ("src", "tests", "scripts")
LIMIT = 15


def _complexipy(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("complexipy", path=str(Path(sys.executable).parent))
    assert executable is not None, "complexipy is not installed next to Python"
    return subprocess.run(
        [executable, "--failed", "--color", "no", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _function_at(complexity: int) -> str:
    """Source of a function whose cognitive complexity is ``complexity``.

    Each ``if`` at the top level of the function adds one.
    """
    branches = "".join(f"    if x == {i}:\n        x += 1\n" for i in range(complexity))
    return f"def branchy(x):\n{branches}    return x\n"


def _copy_config(tmp_path: Path) -> None:
    shutil.copy(CONFIG, tmp_path / CONFIG.name)


def _project_with(tmp_path: Path, source: str) -> Path:
    _copy_config(tmp_path)
    for name in CHECKED_PATHS:
        (tmp_path / name).mkdir()
    (tmp_path / "src" / "probe.py").write_text(source, encoding="utf-8")
    return tmp_path


def _skip_non_python(directory: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name in {"__pycache__", ".complexipy_cache"}
        or (not name.endswith(".py") and not (Path(directory) / name).is_dir())
    }


class TestTheLimit:
    def test_the_project_config_sets_the_limit_and_paths(self):
        with CONFIG.open("rb") as config:
            settings = tomllib.load(config)["tool"]["complexipy"]

        assert settings["max-complexity-allowed"] == LIMIT
        assert settings["paths"] == list(CHECKED_PATHS)

    def test_no_other_config_file_overrides_the_project_config(self):
        # complexipy reads complexipy.toml in preference to pyproject.toml.
        assert not (ROOT / "complexipy.toml").exists()

    def test_a_function_at_the_limit_passes(self, tmp_path: Path):
        result = _complexipy(_project_with(tmp_path, _function_at(LIMIT)))

        assert result.returncode == 0, result.stdout + result.stderr

    def test_a_function_over_the_limit_fails(self, tmp_path: Path):
        result = _complexipy(_project_with(tmp_path, _function_at(LIMIT + 1)))

        assert result.returncode == 1, result.stdout + result.stderr
        assert "branchy" in result.stdout

    def test_an_ignore_comment_does_not_exempt_a_function(self, tmp_path: Path):
        source = _function_at(LIMIT + 1).replace(
            "def branchy(x):", "def branchy(x):  # noqa: complexipy"
        )

        result = _complexipy(_project_with(tmp_path, source))

        assert result.returncode == 1, result.stdout + result.stderr
        assert "branchy" in result.stdout


class TestTheSnapshot:
    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        """A project whose snapshot lists one function over the limit."""
        project = _project_with(tmp_path, _function_at(LIMIT + 2))
        created = _complexipy(project, "--snapshot-create")
        assert created.returncode == 0, created.stdout + created.stderr
        assert "branchy" in (project / SNAPSHOT.name).read_text(encoding="utf-8")
        return project

    def test_a_listed_function_passes(self, project: Path):
        result = _complexipy(project)

        assert result.returncode == 0, result.stdout + result.stderr

    def test_a_listed_function_that_grows_fails(self, project: Path):
        listed = (project / SNAPSHOT.name).read_text(encoding="utf-8")
        (project / "src" / "probe.py").write_text(
            _function_at(LIMIT + 3), encoding="utf-8"
        )

        result = _complexipy(project)

        assert result.returncode == 1, result.stdout + result.stderr
        assert (project / SNAPSHOT.name).read_text(encoding="utf-8") == listed

    def test_a_listed_function_that_shrinks_lowers_its_entry(self, project: Path):
        (project / "src" / "probe.py").write_text(
            _function_at(LIMIT + 1), encoding="utf-8"
        )

        result = _complexipy(project)

        assert result.returncode == 0, result.stdout + result.stderr
        snapshot = json.loads((project / SNAPSHOT.name).read_text(encoding="utf-8"))
        assert snapshot[0]["functions"] == [
            {"name": "branchy", "complexity": LIMIT + 1}
        ]

    def test_a_new_function_over_the_limit_fails(self, project: Path):
        (project / "src" / "unlisted.py").write_text(
            _function_at(LIMIT + 1), encoding="utf-8"
        )

        result = _complexipy(project)

        assert result.returncode == 1, result.stdout + result.stderr
        assert "unlisted.py" in result.stdout

    def test_a_listed_function_under_the_limit_drops_out(self, project: Path):
        (project / "src" / "probe.py").write_text(_function_at(LIMIT), encoding="utf-8")

        result = _complexipy(project)

        assert result.returncode == 0, result.stdout + result.stderr
        snapshot = json.loads((project / SNAPSHOT.name).read_text(encoding="utf-8"))
        assert snapshot == []


class TestTheRepository:
    def test_the_repository_passes_against_its_snapshot(self, tmp_path: Path):
        committed = SNAPSHOT.read_bytes()
        _copy_config(tmp_path)
        shutil.copy(SNAPSHOT, tmp_path / SNAPSHOT.name)
        for name in CHECKED_PATHS:
            shutil.copytree(ROOT / name, tmp_path / name, ignore=_skip_non_python)

        result = _complexipy(tmp_path)

        assert result.returncode == 0, (
            "A function is over the cognitive complexity limit and the snapshot "
            "does not list it at that complexity or higher. Split the function "
            "along what it does.\n" + result.stdout + result.stderr
        )
        assert (tmp_path / SNAPSHOT.name).read_text(encoding="utf-8") == (
            SNAPSHOT.read_text(encoding="utf-8")
        ), (
            "A function the snapshot lists is now less complex. Run "
            "`complexipy` at the repository root and commit the rewritten "
            f"{SNAPSHOT.name}."
        )
        assert SNAPSHOT.read_bytes() == committed
