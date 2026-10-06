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

A second run copies each scaffold the way SKILL.md tells an agent to use one
in a project. The part above the ``# --- Tests ---`` line becomes the project
package ``myapp``, the part below it becomes ``tests/test_<name>.py`` importing
from ``myapp``, and the ``tests/conftest.py`` block of SKILL.md Step 7 sits at
the root of the tests.

A scaffold passes when pytest exits 0 and its JUnit report shows that every
``test_`` function in the asset passed, by name, so a module that collects no
tests, or a test pytest does not collect, fails too.
"""

from __future__ import annotations

import ast
import os
import re
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
SKILL_MD = ASSETS_DIR.parent / "SKILL.md"
TESTS_MARKER = "# --- Tests ---"

# Variables that would make the child run under a configuration other than the
# framework default.
_ISOLATED_VARS = (
    "PROTEAN_ENV",
    "DOMAIN_ROOT_PATH",
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
)


@dataclass(frozen=True)
class Outcome:
    returncode: int
    passed: frozenset[str]
    not_passed: int
    output: str


def declared_tests(source: str) -> frozenset[str]:
    """Name the ``test_`` functions in ``source`` as ``Class.test`` or ``test``."""
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef):
            names.update(
                f"{node.name}.{member.name}"
                for member in node.body
                if isinstance(member, ast.FunctionDef)
                and member.name.startswith("test_")
            )
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            names.add(node.name)
    return frozenset(names)


def _case_name(case: ET.Element, module: str) -> str:
    """Turn a JUnit test case into ``Class.test`` or ``test``, without parameters."""
    owner = case.get("classname", "").rsplit(".", 1)[-1]
    name = re.sub(r"\[.*\]$", "", case.get("name", ""))
    return name if owner == module else f"{owner}.{name}"


def _run_pytest(workdir: Path, target: Path, module: str) -> Outcome:
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
            str(target),
        ],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    passed = set()
    not_passed = 0
    if report.exists():
        for case in ET.parse(report).getroot().iter("testcase"):
            if any(child.tag in ("failure", "error", "skipped") for child in case):
                not_passed += 1
            else:
                passed.add(_case_name(case, module))
    return Outcome(
        returncode=completed.returncode,
        passed=frozenset(passed),
        not_passed=not_passed,
        output=completed.stdout + completed.stderr,
    )


def run_scaffold(scaffold: Path, conftest: Path, workdir: Path) -> Outcome:
    """Copy ``scaffold`` and ``conftest`` into ``workdir`` and run pytest there."""
    module = f"test_{scaffold.stem}"
    shutil.copy(conftest, workdir / "conftest.py")
    shutil.copy(scaffold, workdir / f"{module}.py")
    return _run_pytest(workdir, workdir, module)


def step7_conftest() -> str:
    """Return the ``tests/conftest.py`` block that SKILL.md Step 7 teaches."""
    blocks = re.findall(
        r"```python\n(.*?)```", SKILL_MD.read_text(encoding="utf-8"), re.DOTALL
    )
    matches = [block for block in blocks if "# tests/conftest.py" in block]
    assert len(matches) == 1, "SKILL.md has no single tests/conftest.py block"
    return matches[0]


def run_in_project(scaffold: Path, workdir: Path) -> Outcome:
    """Split ``scaffold`` into a ``myapp`` package and a test module, and run it.

    This is the layout SKILL.md tells an agent to use: the domain lives in the
    project, the test module imports from it, and the Step 7 conftest sets up
    the domain.
    """
    source = scaffold.read_text(encoding="utf-8")
    domain_part, marker, tests_part = source.partition(TESTS_MARKER)
    assert marker, f"{scaffold.name} has no {TESTS_MARKER!r} line"
    module = f"test_{scaffold.stem}"
    (workdir / "myapp").mkdir()
    (workdir / "myapp" / "__init__.py").write_text(domain_part, encoding="utf-8")
    tests_dir = workdir / "tests"
    tests_dir.mkdir()
    (tests_dir / "conftest.py").write_text(step7_conftest(), encoding="utf-8")
    (tests_dir / f"{module}.py").write_text(
        "from myapp import *  # noqa: F403\n" + tests_part, encoding="utf-8"
    )
    return _run_pytest(workdir, tests_dir, module)


def problems_for(scaffold: Path, outcome: Outcome) -> list[str]:
    """Return why ``outcome`` is not a clean pass of every test in ``scaffold``."""
    expected = declared_tests(scaffold.read_text(encoding="utf-8"))
    problems = []
    if not expected:
        problems.append(f"{scaffold.name} defines no test_ functions")
    if outcome.returncode != 0:
        problems.append(f"pytest exited {outcome.returncode}")
    if outcome.not_passed:
        problems.append(f"{outcome.not_passed} tests did not pass")
    if missing := sorted(expected - outcome.passed):
        problems.append(f"did not pass: {', '.join(missing)}")
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


@pytest.mark.parametrize("scaffold", SCAFFOLDS, ids=lambda path: path.stem)
def test_scaffold_tests_pass_in_a_project_with_the_step7_conftest(scaffold, tmp_path):
    outcome = run_in_project(scaffold, tmp_path)
    assert problems_for(scaffold, outcome) == [], outcome.output


def _calls(source: str) -> set[str]:
    """Name every function or method called in ``source``."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(lambda: CONFTEST.read_text(encoding="utf-8"), id="asset"),
        pytest.param(step7_conftest, id="step7"),
    ],
)
def test_conftests_set_up_the_domain_with_domain_fixture(source):
    calls = _calls(source())
    assert {"DomainFixture", "setup", "teardown", "domain_context"} <= calls
    # The domain is never set up by hand.
    assert "init" not in calls


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
    assert problems_for(scaffold, outcome) == [
        "pytest exited 1",
        "2 tests did not pass",
        (
            "did not pass: "
            "TestCrossAggregateFlow.test_multiple_orders_accumulate_reservations, "
            "TestCrossAggregateFlow.test_order_placed_reserves_inventory"
        ),
    ]


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
        "did not pass: test_fails",
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


def test_declared_tests_reads_module_and_class_level_tests():
    source = (
        "def test_a(): pass\n"
        "def helper(): pass\n"
        "class TestX:\n"
        "    def test_b(self): pass\n"
        "    def setup(self): pass\n"
    )
    assert declared_tests(source) == {"test_a", "TestX.test_b"}


def test_an_uncollected_test_is_reported_even_when_the_count_matches(tmp_path):
    # Two passes from one parametrized test must not stand in for a class
    # pytest skips because it defines __init__.
    scaffold, workdir = _synthetic(
        tmp_path,
        "import pytest\nfrom protean import Domain\n\ndomain = Domain()\n\n\n"
        "@pytest.mark.parametrize('n', [1, 2])\n"
        "def test_param(n):\n    assert n\n\n\n"
        "class TestB:\n    def __init__(self):\n        pass\n\n"
        "    def test_b(self):\n        assert True\n",
    )
    outcome = run_scaffold(scaffold, CONFTEST, workdir)
    assert outcome.passed == {"test_param"}
    assert problems_for(scaffold, outcome) == ["did not pass: TestB.test_b"]
