"""Run the generate-test-scaffold assets as pytest modules and require them to pass.

``tests/dx/test_examples.py`` only imports each asset and initializes its
domain. That proves nothing about whether the tests a scaffold teaches pass.
This test copies each ``scaffold_*.py`` asset, renamed ``test_<name>.py``, into
an empty directory next to the skill's ``conftest.py``, the way a user copies
them into a project. It then runs pytest there in a child process.

The child runs under default configuration. The directory has no
``pyproject.toml``, no ``domain.toml`` and none of this repository's
``conftest.py`` files, and ``PROTEAN_ENV`` and ``DOMAIN_ROOT_PATH`` are removed
from its environment. The protean pytest plugin still loads through its entry
point, as it does in a user's project.

A scaffold passes when pytest exits 0 and its JUnit report shows every
``test_`` function in the asset passed, so a module that collects no tests
fails too.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pytest

from protean import dx

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSETS_DIR = PACK_ROOT / dx.SKILLS_DIR / "generate-test-scaffold" / "assets"

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the scaffolds are copied by path",
        allow_module_level=True,
    )

SCAFFOLDS = sorted(ASSETS_DIR.glob("scaffold_*.py"))
CONFTEST = ASSETS_DIR / "conftest.py"

# Variables that would make the child run under a configuration other than the
# framework default.
_ISOLATED_VARS = ("PROTEAN_ENV", "DOMAIN_ROOT_PATH", "PYTEST_ADDOPTS")


@dataclass(frozen=True)
class Outcome:
    returncode: int
    passed: int
    not_passed: int
    output: str


def count_test_functions(source: str) -> int:
    """Count the ``test_`` functions in ``source``, at module level or in a class."""
    total = 0
    for node in ast.parse(source).body:
        members = node.body if isinstance(node, ast.ClassDef) else [node]
        total += sum(
            1
            for member in members
            if isinstance(member, ast.FunctionDef) and member.name.startswith("test_")
        )
    return total


def run_scaffold(scaffold: Path, conftest: Path, workdir: Path) -> Outcome:
    """Copy ``scaffold`` and ``conftest`` into ``workdir`` and run pytest there."""
    shutil.copy(conftest, workdir / "conftest.py")
    shutil.copy(scaffold, workdir / f"test_{scaffold.stem}.py")
    report = workdir / "report.xml"
    env = {k: v for k, v in os.environ.items() if k not in _ISOLATED_VARS}
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--rootdir={workdir}",
            f"--junitxml={report}",
            str(workdir),
        ],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    passed = not_passed = 0
    if report.exists():
        for case in ET.parse(report).getroot().iter("testcase"):
            if any(child.tag in ("failure", "error", "skipped") for child in case):
                not_passed += 1
            else:
                passed += 1
    return Outcome(
        returncode=completed.returncode,
        passed=passed,
        not_passed=not_passed,
        output=completed.stdout + completed.stderr,
    )


def problems_for(scaffold: Path, outcome: Outcome) -> list[str]:
    """Return why ``outcome`` is not a clean pass of every test in ``scaffold``."""
    expected = count_test_functions(scaffold.read_text(encoding="utf-8"))
    problems = []
    if expected == 0:
        problems.append(f"{scaffold.name} defines no test_ functions")
    if outcome.returncode != 0:
        problems.append(f"pytest exited {outcome.returncode}")
    if outcome.not_passed:
        problems.append(f"{outcome.not_passed} tests did not pass")
    if outcome.passed != expected:
        problems.append(f"{outcome.passed} tests passed, expected {expected}")
    return problems


def test_scaffold_discovery_is_not_vacuous():
    assert [path.name for path in SCAFFOLDS] == [
        "scaffold_aggregate_unit.py",
        "scaffold_command_flow.py",
        "scaffold_event_driven_flow.py",
    ]
    assert CONFTEST.is_file()


@pytest.mark.parametrize("scaffold", SCAFFOLDS, ids=lambda path: path.stem)
def test_scaffold_tests_pass_under_default_config(scaffold, tmp_path):
    outcome = run_scaffold(scaffold, CONFTEST, tmp_path)
    assert problems_for(scaffold, outcome) == [], outcome.output


def test_the_event_driven_scaffold_needs_the_conftest_sync_setting(tmp_path):
    # Without the conftest's "sync" settings, the event handler does not run
    # when the Order is persisted, so the cross-aggregate tests fail.
    conftest = tmp_path / "source" / "conftest.py"
    conftest.parent.mkdir()
    conftest.write_text(
        "\n".join(
            line
            for line in CONFTEST.read_text(encoding="utf-8").splitlines()
            if '_processing"] = "sync"' not in line
        ),
        encoding="utf-8",
    )
    workdir = tmp_path / "run"
    workdir.mkdir()
    scaffold = ASSETS_DIR / "scaffold_event_driven_flow.py"

    outcome = run_scaffold(scaffold, conftest, workdir)

    assert outcome.returncode == 1
    assert outcome.not_passed == 2
    assert "tests did not pass" in " ".join(problems_for(scaffold, outcome))


# --- Negative tests on synthetic scaffolds -----------------------------------


def _synthetic(tmp_path: Path, source: str) -> tuple[Path, Path]:
    scaffold = tmp_path / "source" / "scaffold_synthetic.py"
    scaffold.parent.mkdir()
    scaffold.write_text(source, encoding="utf-8")
    workdir = tmp_path / "run"
    workdir.mkdir()
    return scaffold, workdir


def test_a_failing_scaffold_test_is_reported(tmp_path):
    scaffold, workdir = _synthetic(
        tmp_path,
        "from protean import Domain\n\ndomain = Domain()\n\n\n"
        "def test_passes():\n    assert True\n\n\n"
        "def test_fails():\n    assert 1 == 2\n",
    )
    outcome = run_scaffold(scaffold, CONFTEST, workdir)
    assert problems_for(scaffold, outcome) == [
        "pytest exited 1",
        "1 tests did not pass",
        "1 tests passed, expected 2",
    ]


def test_a_scaffold_with_no_tests_is_reported(tmp_path):
    scaffold, workdir = _synthetic(
        tmp_path, "from protean import Domain\n\ndomain = Domain()\n"
    )
    outcome = run_scaffold(scaffold, CONFTEST, workdir)
    assert problems_for(scaffold, outcome) == [
        "scaffold_synthetic.py defines no test_ functions",
        "pytest exited 5",
    ]


def test_count_test_functions_reads_module_and_class_level_tests():
    source = (
        "def test_a(): pass\n"
        "def helper(): pass\n"
        "class TestX:\n"
        "    def test_b(self): pass\n"
        "    def setup(self): pass\n"
    )
    assert count_test_functions(source) == 2
