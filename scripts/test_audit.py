#!/usr/bin/env python3
"""Rank the core test suite's duplicate, private-state, slow and order-dependent tests.

    make test-audit        # or: uv run python scripts/test_audit.py [--seed N]

Three stages run against the core lane (no Docker), and their results go to
``.test-audit/report.md`` and ``.test-audit/report.json``:

1. **Coverage contexts.** The suite runs under coverage.py, and a small
   pytest hook in this file switches coverage.py's context to each test's node
   ID while the test body runs, so every arc is recorded against the test that
   ran it. A test is a duplicate candidate when its arcs are a subset of one
   other test's arcs.
2. **Static scan.** An ``ast`` pass over ``tests/`` flags tests that reach into
   private state, and files or comments that say they exist for coverage.
3. **Random order.** pytest-randomly shuffles the suite with a recorded seed.
   The run gives the 50 slowest tests. A failure that also failed in the
   default-order coverage run is a plain failure. Every other failure is
   re-run alone, and one that passes alone is listed as order-dependent. One
   that is skipped or xfailed alone is listed apart, since the re-run did not
   say whether it passes.

The report ranks candidates. It changes and deletes no test; the only files
it writes or removes are its own, under ``.test-audit/``. The script exits 0
when all three stages ran, whatever the report lists, and non-zero only when a
stage could not run.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import random
import re
import subprocess
import sys
import tokenize
import tomllib
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pytest
from coverage import Coverage, CoverageData

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / ".test-audit"
TESTS = "tests"
# This file as a pytest plugin, importable from the repo root, which is the
# working directory of every suite run.
PLUGIN = "scripts.test_audit"

# The core lane, as `protean test` runs it, without its `--cache-clear`: the
# audit must not write to or clear the repo's `.pytest_cache`.
CORE_ARGS = ["--ignore=tests/support/", "-p", "no:cacheprovider"]
# Spread both suite runs over every CPU, as CORE does. `loadfile` keeps each
# file on one worker, so module-level caches are computed once.
XDIST_ARGS = ["-n", "logical", "--dist", "loadfile"]

SLOWEST = 50

# pytest exit codes 0 (all passed) and 1 (some failed) mean the suite ran.
RAN = {0, 1}

COVERAGE_CLAIM = re.compile(
    r"(?i)\b(to (increase|improve|raise) coverage|uncovered lines?|coverage gaps?"
    r"|explicit test coverage|for coverage)\b"
)

# Files the static scan skips entirely. They guard documentation or
# deprecation coverage, so their wording matches the scan without the file
# being a test written for coverage numbers.
EXCLUDED: dict[str, str] = {
    "tests/test_doc_coverage.py": (
        "checks that public API is documented; 'coverage' here means doc coverage"
    ),
    "tests/ir/test_deprecation_coverage_audit.py": (
        "checks that every deprecation has a test; 'coverage' here means deprecation coverage"
    ),
}

PATCH_OBJECT_CALLS = {
    "patch.object",
    "mock.patch.object",
    "unittest.mock.patch.object",
    "mocker.patch.object",
}
PATCH_TARGET_CALLS = {"patch", "mock.patch", "unittest.mock.patch", "mocker.patch"}
MONKEYPATCH_CALLS = {"monkeypatch.setattr", "monkeypatch.delattr"}
# Test doubles a test builds and owns outright, so writing a private name on
# one is setting up the double, not reaching into the code under test.
TEST_DOUBLE_FACTORIES = {
    "Mock",
    "MagicMock",
    "AsyncMock",
    "NonCallableMock",
    "SimpleNamespace",
}


# ---------------------------------------------------------------------------
# Stage 1: coverage contexts and the subset search
# ---------------------------------------------------------------------------


def coverage_rc(pyproject: Path, data_file: Path) -> str:
    """The TOML text of the audit's coverage config.

    It repeats ``[tool.coverage.run]`` and ``[tool.coverage.paths]`` from
    ``pyproject.toml`` as they are, so the audit measures what CI measures, and
    points the data file inside ``.test-audit/``. The ``ctrace`` core is set
    because the ``sysmon`` core, the default on Python 3.14, does not record
    contexts set with ``switch_context``. A ``dynamic_context`` in pyproject is
    dropped: it would start its own contexts and fight the per-test hook.
    """
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    coverage = config.get("tool", {}).get("coverage", {})
    run = dict(coverage.get("run", {}))
    run.pop("dynamic_context", None)
    run["core"] = "ctrace"
    run["data_file"] = str(data_file)
    lines = [_toml_table("tool.coverage.run", run)]
    if "paths" in coverage:
        lines.append(_toml_table("tool.coverage.paths", coverage["paths"]))
    return "\n".join(lines)


def _toml_table(name: str, values: Mapping[str, Any]) -> str:
    body = "".join(
        f"{_toml_value(key)} = {_toml_value(value)}\n" for key, value in values.items()
    )
    return f"[{name}]\n{body}"


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        # Without ensure_ascii=False, json writes a character outside the BMP
        # as a surrogate pair, which TOML rejects.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise TypeError(f"cannot write {value!r} into the coverage config")


def function_id(nodeid: str) -> str:
    """A node ID without its parametrize suffix: the unit a context covers."""
    return nodeid.split("[", 1)[0]


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Any:
    """Record the test body's arcs under the test's function ID.

    The audit loads this file as a plugin (``-p``) in its coverage run, and
    pytest-xdist workers load it too. A child pytest that a test starts does
    not get the flag, so the child's arcs go to the empty context, which the
    analysis drops. Fixture setup and teardown run outside this hook, so their
    arcs go to the empty context as well.
    """
    cov = Coverage.current()
    if cov is None:
        return (yield)
    cov.switch_context(function_id(item.nodeid))
    try:
        return (yield)
    finally:
        cov.switch_context("")


def junit_key(nodeid: str) -> tuple[str, str]:
    """The ``(classname, name)`` pytest's JUnit XML writes for ``nodeid``.

    Mirrors ``_pytest.junitxml.mangle_test_address``.
    """
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


@dataclass(frozen=True)
class Duplicate:
    test: str
    covered_by: str
    arcs: int
    covering_arcs: int


def load_arcsets(data: Any, tests: Iterable[str]) -> dict[str, frozenset[int]]:
    """Per-test arc sets from a combined ``CoverageData``.

    ``tests`` holds the context names to keep, one per test function. Every
    other context, such as the empty one (import time, fixtures, child
    processes), is dropped here. Arcs are interned as integers, because the
    full suite records millions of them.
    """
    keep = set(tests)
    data.set_query_contexts(None)
    touched: dict[str, set[str]] = defaultdict(set)
    for filename in data.measured_files():
        for contexts in data.contexts_by_lineno(filename).values():
            for context in contexts:
                if context in keep:
                    touched[context].add(filename)

    ids: dict[tuple[str, int, int], int] = {}
    arcsets: dict[str, set[int]] = defaultdict(set)
    for context, filenames in touched.items():
        data.set_query_context(context)
        arcs = arcsets[context]
        for filename in filenames:
            for start, end in data.arcs(filename) or ():
                arcs.add(ids.setdefault((filename, start, end), len(ids)))
    data.set_query_contexts(None)
    return {test: frozenset(arcs) for test, arcs in arcsets.items()}


def find_duplicates(arcsets: Mapping[str, frozenset[Any]]) -> list[Duplicate]:
    """Tests whose arcs are a subset of one other test's arcs.

    Each candidate names the covering test with the smallest arc set, and the
    node ID that sorts first breaks a tie. When two tests have identical arcs,
    the one that sorts first is the covering test, so the pair appears once.
    Tests with no arcs are left out; they are listed apart.
    """
    postings: dict[Any, list[str]] = defaultdict(list)
    for name in sorted(arcsets):
        for arc in arcsets[name]:
            postings[arc].append(name)

    duplicates = []
    for name in sorted(arcsets):
        arcs = arcsets[name]
        if not arcs:
            continue
        # Every covering test has the test's rarest arc, so only the tests that
        # share that arc need the full subset check.
        rarest = min(arcs, key=lambda arc: len(postings[arc]))
        best: str | None = None
        for other in postings[rarest]:
            if other == name:
                continue
            other_arcs = arcsets[other]
            if not arcs <= other_arcs:
                continue
            if other_arcs == arcs and other > name:
                continue
            if best is None or (len(other_arcs), other) < (len(arcsets[best]), best):
                best = other
        if best is not None:
            duplicates.append(Duplicate(name, best, len(arcs), len(arcsets[best])))
    return duplicates


def analyse_coverage(
    data: Any, nodeids: Iterable[str], outcomes: Iterable[Outcome]
) -> tuple[list[Duplicate], list[str]]:
    """The duplicate candidates, and the tests that ran with no arcs of their own.

    Parametrized cases share one context, so the unit is the test function. A
    function with a case that failed in this run is left out of both lists:
    its arcs stop where it broke, so a subset would say nothing. A skipped
    test records no arcs, so it is not listed as having none.
    """
    outcomes = list(outcomes)
    broken = {function_id(o.nodeid) for o in outcomes if o.failed}
    tests = {function_id(nodeid) for nodeid in nodeids} - broken
    arcsets = load_arcsets(data, tests)
    for outcome in outcomes:
        test = function_id(outcome.nodeid)
        if not outcome.skipped and test in tests:
            arcsets.setdefault(test, frozenset())
    no_arcs = sorted(test for test, arcs in arcsets.items() if not arcs)
    return find_duplicates(arcsets), no_arcs


def top_level_dir(nodeid: str) -> str:
    """``tests/<dir>`` for a test in a subdirectory, ``tests`` for a root file."""
    parts = nodeid.split("::", 1)[0].split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def group_by_dir(duplicates: Iterable[Duplicate]) -> dict[str, list[Duplicate]]:
    groups: dict[str, list[Duplicate]] = defaultdict(list)
    for duplicate in duplicates:
        groups[top_level_dir(duplicate.test)].append(duplicate)
    return dict(sorted(groups.items()))


# ---------------------------------------------------------------------------
# Stage 2: the static scan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    detail: str


def _is_private(name: str) -> bool:
    """A single-underscore or name-mangled name. Dunders such as ``__init__``
    are protocol hooks, not private state, so they are not flagged."""
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _argument(call: ast.Call, position: int, keyword: str) -> str | None:
    """The string passed at ``position`` or as ``keyword=``, if either is a literal."""
    if len(call.args) > position:
        return _string(call.args[position])
    for kw in call.keywords:
        if kw.arg == keyword:
            return _string(kw.value)
    return None


class _PrivateStateVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self._class_depth = 0
        # Names bound to a test double, one set per function scope.
        self._doubles: list[set[str]] = [set()]

    def _flag(self, node: ast.expr, kind: str, detail: str) -> None:
        self.findings.append(Finding(self.path, node.lineno, kind, detail))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_depth += 1
        self.generic_visit(node)
        self._class_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._doubles.append(set())
        self.generic_visit(node)
        self._doubles.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = _dotted(func)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "__new__"
            and isinstance(func.value, ast.Name)
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == func.value.id
        ):
            self._flag(node, "__new__", f"{func.value.id}.__new__({func.value.id})")
        elif name in MONKEYPATCH_CALLS and node.args and _string(node.args[0]):
            # The string form, ``setattr("pkg.mod.name", value)``: the
            # second argument is the value, not a name.
            self._flag_target(node, name, _string(node.args[0]))
        elif name in PATCH_OBJECT_CALLS | MONKEYPATCH_CALLS or (
            name == "setattr"
            and not self._own_state(node.args[0] if node.args else None)
        ):
            attr = _argument(node, 1, "attribute")
            if attr is not None and _is_private(attr):
                self._flag(node, "patch", f'{name}(..., "{attr}")')
        elif name in PATCH_TARGET_CALLS:
            self._flag_target(node, name, _argument(node, 0, "target"))
        self.generic_visit(node)

    def _flag_target(self, node: ast.Call, name: str, target: str | None) -> None:
        if target and _is_private(target.rsplit(".", 1)[-1]):
            self._flag(node, "patch", f'{name}("{target}")')

    def _own_state(self, owner: ast.expr | None) -> bool:
        """``self`` or ``cls`` inside a class of the test module: a test class
        setting up its own state is not reaching into the code under test."""
        return bool(
            self._class_depth
            and isinstance(owner, ast.Name)
            and owner.id in {"self", "cls"}
        )

    def _check_target(self, target: ast.expr) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._check_target(element)
            return
        if not isinstance(target, ast.Attribute) or not _is_private(target.attr):
            return
        if self._own_state(target.value):
            return
        if isinstance(target.value, ast.Name) and target.value.id in self._doubles[-1]:
            return
        owner = _dotted(target.value) or "<expr>"
        self._flag(target, "assignment", f"{owner}.{target.attr} = ...")

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_target(target)
        self._note_doubles(node.targets, node.value)
        self.generic_visit(node)

    def _note_doubles(self, targets: list[ast.expr], value: ast.expr | None) -> None:
        if isinstance(value, ast.Call):
            factory = _dotted(value.func) or ""
            if factory.rsplit(".", 1)[-1] in TEST_DOUBLE_FACTORIES:
                self._doubles[-1].update(
                    target.id for target in targets if isinstance(target, ast.Name)
                )

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_target(node.target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_target(node.target)
        self._note_doubles([node.target], node.value)
        self.generic_visit(node)


def scan_private_state(path: str, source: str) -> list[Finding]:
    """Calls to ``X.__new__(X)``, writes to another object's private
    attributes, and patches of private names.

    A write is not flagged when it goes through ``self`` or ``cls`` inside a
    class the test module defines, or to a mock or ``SimpleNamespace`` the same
    function created. A private write to any other object is flagged, even
    when the test built that object itself."""
    visitor = _PrivateStateVisitor(path)
    visitor.visit(ast.parse(source, filename=path))
    return visitor.findings


def scan_coverage_named(path: str, source: str) -> list[Finding]:
    """A ``*_coverage.py`` file name, and docstrings or ``#`` comments that say
    the test exists for coverage. The bare word "coverage" matches nothing."""
    findings = []
    if path.endswith("_coverage.py"):
        findings.append(Finding(path, 1, "file name", Path(path).name))
    tree = ast.parse(source, filename=path)
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            docstring = ast.get_docstring(node)
            match = COVERAGE_CLAIM.search(docstring or "")
            if match:
                line = node.body[0].lineno
                findings.append(Finding(path, line, "docstring", match.group(0)))
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            match = COVERAGE_CLAIM.search(token.string)
            if match:
                findings.append(
                    Finding(path, token.start[0], "comment", match.group(0))
                )
    return sorted(findings, key=lambda finding: finding.line)


def static_scan(root: Path) -> tuple[list[Finding], list[Finding]]:
    private: list[Finding] = []
    coverage_named: list[Finding] = []
    for file in sorted((root / TESTS).rglob("*.py")):
        path = file.relative_to(root).as_posix()
        if path in EXCLUDED or path.startswith(f"{TESTS}/support/"):
            continue
        # ``utf-8-sig`` drops a byte-order mark, which ``ast.parse`` rejects.
        source = file.read_text(encoding="utf-8-sig")
        try:
            private += scan_private_state(path, source)
            coverage_named += scan_coverage_named(path, source)
        except (SyntaxError, tokenize.TokenError) as exc:
            raise StageError(f"the static scan could not parse {path}: {exc}") from exc
    return private, coverage_named


# ---------------------------------------------------------------------------
# Stage 3: the random-order run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    nodeid: str
    seconds: float
    failed: bool
    skipped: bool


def read_junit(xml: Path, nodeids: Iterable[str]) -> list[Outcome]:
    """Outcomes from pytest's JUnit XML, keyed back to node IDs."""
    by_key = {junit_key(nodeid): nodeid for nodeid in nodeids}
    outcomes = []
    for case in ET.parse(xml).getroot().iter("testcase"):
        key = (case.get("classname", ""), case.get("name", ""))
        nodeid = by_key.get(key, "::".join(part for part in key if part))
        outcomes.append(
            Outcome(
                nodeid=nodeid,
                seconds=float(case.get("time", "0")),
                failed=case.find("failure") is not None
                or case.find("error") is not None,
                skipped=case.find("skipped") is not None,
            )
        )
    return outcomes


def slowest(outcomes: Iterable[Outcome], limit: int = SLOWEST) -> list[Outcome]:
    return sorted(outcomes, key=lambda outcome: (-outcome.seconds, outcome.nodeid))[
        :limit
    ]


def rerun_result(outcomes: Iterable[Outcome], nodeid: str) -> str:
    """``"passed"``, ``"failed"`` or ``"skipped"`` for ``nodeid`` in a re-run.

    pytest exits 0 when the only test is skipped or xfailed, so the exit code
    alone cannot say the test passed.
    """
    mine = [outcome for outcome in outcomes if outcome.nodeid == nodeid]
    if not mine:
        raise StageError(f"re-running {nodeid} alone reported no result for it")
    if any(outcome.failed for outcome in mine):
        return "failed"
    if any(outcome.skipped for outcome in mine):
        return "skipped"
    return "passed"


def classify_failures(
    failed: Iterable[str],
    rerun_alone: Callable[[str], str],
    failed_in_default_order: Iterable[str] = (),
) -> tuple[list[str], list[str], list[str]]:
    """Split shuffled-run failures into (order-dependent, plain failures,
    skipped alone).

    A test that passes when re-run alone in default order likely failed
    because of what ran before it, though a flaky test passes alone too. A test
    that also failed in the coverage run, which keeps the default order, is a
    plain failure without a re-run.
    """
    default_failures = set(failed_in_default_order)
    order_dependent: list[str] = []
    plain: list[str] = []
    skipped_alone: list[str] = []
    for nodeid in sorted(set(failed)):
        result = "failed" if nodeid in default_failures else rerun_alone(nodeid)
        if result == "passed":
            order_dependent.append(nodeid)
        elif result == "skipped":
            skipped_alone.append(nodeid)
        else:
            plain.append(nodeid)
    return order_dependent, plain, skipped_alone


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


@dataclass
class Report:
    seed: int
    duplicates: list[Duplicate]
    no_arcs: list[str]
    private_state: list[Finding]
    coverage_named: list[Finding]
    slowest: list[Outcome]
    order_dependent: list[str]
    plain_failures: list[str]
    skipped_alone: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "duplicates": {
                group: [asdict(duplicate) for duplicate in items]
                for group, items in group_by_dir(self.duplicates).items()
            },
            "no_arcs": self.no_arcs,
            "private_state": [asdict(finding) for finding in self.private_state],
            "coverage_named": [asdict(finding) for finding in self.coverage_named],
            "excluded": EXCLUDED,
            "slowest": [
                {"test": outcome.nodeid, "seconds": outcome.seconds}
                for outcome in self.slowest
            ],
            "order_dependent": self.order_dependent,
            "plain_failures": self.plain_failures,
            "skipped_alone": self.skipped_alone,
        }


def _findings_by_file(findings: Iterable[Finding]) -> list[str]:
    by_file: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        by_file[finding.path].append(finding)
    lines = []
    for path in sorted(by_file):
        lines.append(f"- `{path}`")
        lines.extend(
            f"  - line {finding.line}, {finding.kind}: `{finding.detail}`"
            for finding in by_file[path]
        )
    return lines


def render_markdown(report: Report) -> str:
    out = [
        "# Test audit",
        "",
        (
            "This report ranks candidates for a person to review. It changes "
            "and deletes no test."
        ),
        "",
        "## Duplicate candidates",
        "",
        (
            "Each test's covered arcs are a subset of the arcs of the covering "
            "test. Arcs come from the core lane only, so a test that covers an "
            "adapter path the core lane skips can still be listed."
        ),
        "",
        (
            "Only arcs run during the test body count. Arcs run in fixture "
            "setup and teardown, and in a child process the test starts, are "
            "not counted. Code that runs once per worker process, such as an "
            "import or a cache filled on first use, counts only for the first "
            "test on that worker. A test whose function failed in the coverage "
            "run is left out."
        ),
        "",
    ]
    groups = group_by_dir(report.duplicates)
    if not groups:
        out.append("None.")
    for group, items in groups.items():
        out += [f"### `{group}`", ""]
        out += [
            f"- `{item.test}` ({item.arcs} arcs) is covered by "
            f"`{item.covered_by}` ({item.covering_arcs} arcs)"
            for item in items
        ]
        out.append("")
    out += ["", "### Tests with no covered arcs of their own", ""]
    out += [f"- `{test}`" for test in report.no_arcs] or ["None."]

    out += [
        "",
        "## Private-state and coverage-named tests",
        "",
        "### Private state",
        "",
    ]
    out += _findings_by_file(report.private_state) or ["None."]
    out += ["", "### Coverage-named", ""]
    out += _findings_by_file(report.coverage_named) or ["None."]
    out += ["", "These files are not scanned:", ""]
    out += [f"- `{path}`: {reason}" for path, reason in sorted(EXCLUDED.items())]

    out += [
        "",
        f"## The {SLOWEST} slowest tests",
        "",
        (
            "Timed in the random-order run, without coverage tracing. A time "
            "includes the test's setup and teardown, so the first test on each "
            "worker also carries the session-scoped fixtures."
        ),
        "",
    ]
    out += [
        f"{rank}. `{outcome.nodeid}`: {outcome.seconds:.2f}s"
        for rank, outcome in enumerate(report.slowest, 1)
    ] or ["None."]

    out += [
        "",
        "## Order-dependent tests",
        "",
        (
            f"Seed: `{report.seed}`. Run the audit again with this seed by "
            f"`uv run python scripts/test_audit.py --seed {report.seed}`. The "
            "seed fixes the order inside each file. Files go to workers as the "
            "workers free up, so the order across files can differ."
        ),
        "",
        (
            "These failed in the shuffled run and passed when run alone in "
            "default order. A flaky test, or one that fails only next to "
            "another worker, also passes alone, so check each one:"
        ),
        "",
    ]
    out += [f"- `{test}`" for test in report.order_dependent] or ["None."]
    out += [
        "",
        (
            "These failed in the shuffled run and failed again alone, or "
            "failed in the default-order coverage run too:"
        ),
        "",
    ]
    out += [f"- `{test}`" for test in report.plain_failures] or ["None."]
    out += [
        "",
        (
            "These failed in the shuffled run and were skipped or xfailed "
            "when run alone, so the re-run did not show whether they pass:"
        ),
        "",
    ]
    out += [f"- `{test}`" for test in report.skipped_alone] or ["None."]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Running the suite
# ---------------------------------------------------------------------------


class StageError(RuntimeError):
    """A stage could not run, so the report would be incomplete."""


Runner = Callable[[list[str], Path | None], int]


def run(cmd: list[str], log: Path | None = None) -> int:
    """Run ``cmd`` in the repo and return its exit code.

    With ``log``, the output goes to that file in place of the terminal.
    """
    print("$", " ".join(cmd), flush=True)
    if log is None:
        return subprocess.run(cmd, cwd=REPO, check=False).returncode
    with log.open("w", encoding="utf-8") as handle:
        return subprocess.run(
            cmd, cwd=REPO, stdout=handle, stderr=subprocess.STDOUT, check=False
        ).returncode


def _pytest(*args: str) -> list[str]:
    return [sys.executable, "-m", "pytest", *CORE_ARGS, *args]


def collect(out: Path, runner: Runner = run) -> list[str]:
    """The node ID of every collected test function."""
    cmd = [sys.executable, str(Path(__file__).resolve()), "--_collect", str(out)]
    if runner(cmd, None) != 0 or not out.exists():
        raise StageError("collecting the core suite failed")
    return list(json.loads(out.read_text(encoding="utf-8")))


class _NodeIds:
    """A pytest plugin that writes the collected test functions' node IDs."""

    def __init__(self, out: Path) -> None:
        self.out = out

    def pytest_collection_finish(self, session: Any) -> None:
        nodeids = [
            item.nodeid for item in session.items if isinstance(item, pytest.Function)
        ]
        self.out.write_text(json.dumps(nodeids), encoding="utf-8")


def _collect_main(out: Path) -> int:
    code = pytest.main([*CORE_ARGS, "--co", "-qq"], plugins=[_NodeIds(out)])
    return 0 if code == 0 else int(code)


def coverage_stage(
    nodeids: list[str], out_dir: Path = OUT_DIR, runner: Runner = run
) -> tuple[list[Duplicate], list[str], list[str]]:
    """The duplicate candidates, the tests with no arcs, and the tests that
    failed in this default-order run."""
    rc = out_dir / "coveragerc.toml"
    data_file = out_dir / ".coverage"
    rc.write_text(coverage_rc(REPO / "pyproject.toml", data_file), encoding="utf-8")
    for stale in out_dir.glob(".coverage*"):
        stale.unlink()
    junit = out_dir / "coverage-run.xml"
    coverage = [sys.executable, "-m", "coverage"]
    code = runner(
        [
            *coverage,
            "run",
            "--rcfile",
            str(rc),
            "-m",
            "pytest",
            # The plugin is this file, imported from the repo root.
            "-p",
            PLUGIN,
            *CORE_ARGS,
            *XDIST_ARGS,
            f"--junitxml={junit}",
        ],
        None,
    )
    if code not in RAN:
        raise StageError(f"the coverage run exited {code}")
    if runner([*coverage, "combine", "--rcfile", str(rc)], None) != 0:
        raise StageError("combining the coverage data failed")
    if not data_file.exists():
        raise StageError("the coverage run wrote no data")

    data = CoverageData(basename=str(data_file))
    data.read()
    outcomes = read_junit(junit, nodeids)
    duplicates, no_arcs = analyse_coverage(data, nodeids, outcomes)
    return duplicates, no_arcs, [o.nodeid for o in outcomes if o.failed]


def random_stage(
    seed: int,
    nodeids: list[str],
    failed_in_default_order: Iterable[str] = (),
    out_dir: Path = OUT_DIR,
    runner: Runner = run,
) -> tuple[list[Outcome], list[str], list[str], list[str]]:
    junit = out_dir / "random-run.xml"
    log = out_dir / "random-run.log"
    cmd = _pytest(
        "-p", "randomly", f"--randomly-seed={seed}", *XDIST_ARGS, f"--junitxml={junit}"
    )
    code = runner(cmd, log)
    if code not in RAN:
        raise StageError(f"the random-order run exited {code}; see {log}")
    if f"--randomly-seed={seed}" not in log.read_text(encoding="utf-8"):
        raise StageError("pytest-randomly did not run, so the order was not shuffled")

    rerun_junit = out_dir / "rerun.xml"

    def rerun_alone(nodeid: str) -> str:
        # A stale file from the previous re-run must not stand in for this one.
        rerun_junit.unlink(missing_ok=True)
        code = runner(
            _pytest("-p", "no:randomly", f"--junitxml={rerun_junit}", nodeid), None
        )
        if code not in RAN:
            raise StageError(f"re-running {nodeid} alone exited {code}")
        if not rerun_junit.exists():
            raise StageError(f"re-running {nodeid} alone wrote no JUnit results")
        return rerun_result(read_junit(rerun_junit, [nodeid]), nodeid)

    outcomes = read_junit(junit, nodeids)
    failed = [outcome.nodeid for outcome in outcomes if outcome.failed]
    order_dependent, plain, skipped_alone = classify_failures(
        failed, rerun_alone, failed_in_default_order
    )
    return (
        slowest(o for o in outcomes if not o.skipped),
        order_dependent,
        plain,
        skipped_alone,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--seed", type=int, help="seed for the random-order run")
    parser.add_argument("--_collect", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._collect:
        return _collect_main(args._collect)

    OUT_DIR.mkdir(exist_ok=True)
    seed = args.seed if args.seed is not None else random.randrange(2**32)
    try:
        # The scan is quick, so a file it cannot parse stops the audit before
        # the long suite runs.
        private, coverage_named = static_scan(REPO)
        nodeids = collect(OUT_DIR / "collected.json")
        duplicates, no_arcs, failed_in_default_order = coverage_stage(nodeids)
        times, order_dependent, plain, skipped_alone = random_stage(
            seed, nodeids, failed_in_default_order
        )
    except StageError as exc:
        print(f"test audit: {exc}", file=sys.stderr)
        return 1

    report = Report(
        seed=seed,
        duplicates=duplicates,
        no_arcs=no_arcs,
        private_state=private,
        coverage_named=coverage_named,
        slowest=times,
        order_dependent=order_dependent,
        plain_failures=plain,
        skipped_alone=skipped_alone,
    )
    (OUT_DIR / "report.json").write_text(
        json.dumps(report.to_json(), indent=2) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"test audit: wrote {OUT_DIR / 'report.md'} and {OUT_DIR / 'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
