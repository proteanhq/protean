"""`scripts/test_audit.py`, the script behind `make test-audit`.

The full audit runs the whole core suite several times, so these tests check
its parts on small inputs: the subset search on hand-built coverage data, the
per-test context hook on a tiny project, the static scan, and the two suite
stages with a stubbed runner.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from coverage import CoverageData

REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "test_audit_script", REPO / "scripts" / "test_audit.py"
)
assert _spec is not None and _spec.loader is not None
audit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = audit
_spec.loader.exec_module(audit)

pytestmark = pytest.mark.no_test_domain

MOD = "/src/protean/mod.py"
OTHER = "/src/protean/other.py"


def _data(
    tmp_path: Path, arcs: dict[str, dict[str, list[tuple[int, int]]]]
) -> CoverageData:
    """Coverage data with ``arcs[context][file]`` recorded under each context."""
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    for context, by_file in arcs.items():
        data.set_context(context)
        if by_file:
            data.add_arcs(by_file)
    data.write()
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.read()
    return data


class TestSubsetSearch:
    def test_a_subset_is_reported_with_its_covering_test(self, tmp_path):
        data = _data(
            tmp_path,
            {
                "t.py::test_a": {MOD: [(1, 2), (2, 3)]},
                "t.py::test_b": {MOD: [(1, 2), (2, 3), (3, 4)]},
                "t.py::test_c": {MOD: [(2, 3), (3, 4), (5, 6)]},
            },
        )
        tests = [f"t.py::test_{x}" for x in "abc"]

        duplicates = audit.find_duplicates(audit.load_arcsets(data, tests))

        assert duplicates == [
            audit.Duplicate(
                test="t.py::test_a", covered_by="t.py::test_b", arcs=2, covering_arcs=3
            )
        ]

    def test_the_same_arc_in_another_file_is_a_different_arc(self, tmp_path):
        data = _data(
            tmp_path,
            {
                "t.py::test_a": {MOD: [(1, 2)]},
                "t.py::test_b": {OTHER: [(1, 2)], MOD: [(3, 4)]},
            },
        )

        arcsets = audit.load_arcsets(data, ["t.py::test_a", "t.py::test_b"])

        assert len(arcsets["t.py::test_b"]) == 2
        assert audit.find_duplicates(arcsets) == []

    def test_the_smallest_covering_test_is_named(self):
        arcsets = {
            "t::a": frozenset({1}),
            "t::small": frozenset({1, 2}),
            "t::z_big": frozenset({1, 2, 3}),
        }

        duplicates = audit.find_duplicates(arcsets)

        assert [(d.test, d.covered_by) for d in duplicates] == [
            ("t::a", "t::small"),
            ("t::small", "t::z_big"),
        ]

    def test_a_size_tie_goes_to_the_first_sorting_test(self):
        arcsets = {
            "t::a": frozenset({1}),
            "t::c": frozenset({1, 3}),
            "t::b": frozenset({1, 2}),
        }

        duplicates = audit.find_duplicates(arcsets)

        assert [(d.test, d.covered_by) for d in duplicates] == [("t::a", "t::b")]

    def test_identical_arcs_are_reported_once(self):
        arcsets = {"t::b": frozenset({1, 2}), "t::a": frozenset({1, 2})}

        duplicates = audit.find_duplicates(arcsets)

        assert [(d.test, d.covered_by) for d in duplicates] == [("t::b", "t::a")]

    def test_no_subsets_reports_nothing(self):
        arcsets = {"t::a": frozenset({1, 2}), "t::b": frozenset({2, 3})}

        assert audit.find_duplicates(arcsets) == []

    def test_a_test_with_no_arcs_is_not_a_duplicate(self):
        arcsets = {"t::a": frozenset(), "t::b": frozenset({1})}

        assert audit.find_duplicates(arcsets) == []

    def test_fixture_and_empty_contexts_are_dropped(self, tmp_path):
        data = _data(
            tmp_path,
            {
                "": {MOD: [(1, 2), (2, 3), (3, 4)]},
                "tests.conftest.test_domain": {MOD: [(1, 2), (2, 3), (3, 4)]},
                "t.py::test_a": {MOD: [(1, 2)]},
            },
        )

        arcsets = audit.load_arcsets(data, ["t.py::test_a"])

        assert list(arcsets) == ["t.py::test_a"]
        assert audit.find_duplicates(arcsets) == []


class TestAnalyseCoverage:
    def test_a_test_that_ran_with_no_arcs_is_listed_apart(self, tmp_path):
        data = _data(tmp_path, {"t.py::test_a": {MOD: [(1, 2)]}})
        nodeids = ["t.py::test_a", "t.py::test_empty[1]", "t.py::test_skipped"]
        outcomes = [
            audit.Outcome("t.py::test_a", 0.1, False, False),
            audit.Outcome("t.py::test_empty[1]", 0.1, False, False),
            audit.Outcome("t.py::test_skipped", 0.0, False, True),
        ]

        duplicates, no_arcs = audit.analyse_coverage(data, nodeids, outcomes)

        assert duplicates == []
        assert no_arcs == ["t.py::test_empty"]

    def test_parametrized_cases_report_as_their_function(self, tmp_path):
        data = _data(
            tmp_path,
            {"t.py::test_a": {MOD: [(1, 2)]}, "t.py::test_b": {MOD: [(1, 2), (2, 3)]}},
        )
        nodeids = ["t.py::test_a[1-x]", "t.py::test_a[2-y]", "t.py::test_b"]

        duplicates, _ = audit.analyse_coverage(data, nodeids, [])

        assert [(d.test, d.covered_by) for d in duplicates] == [
            ("t.py::test_a", "t.py::test_b")
        ]

    def test_a_test_that_failed_is_left_out(self, tmp_path):
        data = _data(
            tmp_path,
            {"t.py::test_a": {MOD: [(1, 2)]}, "t.py::test_b": {MOD: [(1, 2), (2, 3)]}},
        )
        nodeids = ["t.py::test_a[1]", "t.py::test_a[2]", "t.py::test_b", "t.py::test_c"]
        outcomes = [
            audit.Outcome("t.py::test_a[1]", 0.1, False, False),
            audit.Outcome("t.py::test_a[2]", 0.1, True, False),
            audit.Outcome("t.py::test_b", 0.1, False, False),
            audit.Outcome("t.py::test_c", 0.1, True, False),
        ]

        duplicates, no_arcs = audit.analyse_coverage(data, nodeids, outcomes)

        assert duplicates == []
        assert no_arcs == []

    def test_a_passing_test_is_not_covered_by_an_xfailed_one(self, tmp_path):
        data = _data(
            tmp_path,
            {"t.py::test_a": {MOD: [(1, 2)]}, "t.py::test_xf": {MOD: [(1, 2), (2, 3)]}},
        )
        nodeids = ["t.py::test_a", "t.py::test_xf"]
        outcomes = [
            audit.Outcome("t.py::test_a", 0.1, False, False),
            audit.Outcome("t.py::test_xf", 0.1, False, True, xfailed=True),
        ]

        duplicates, no_arcs = audit.analyse_coverage(data, nodeids, outcomes)

        assert duplicates == []
        assert no_arcs == []

    def test_a_test_skipped_inside_its_body_is_left_out(self, tmp_path):
        data = _data(
            tmp_path,
            {"t.py::test_a": {MOD: [(1, 2)]}, "t.py::test_sk": {MOD: [(1, 2), (2, 3)]}},
        )
        nodeids = ["t.py::test_a", "t.py::test_sk[1]", "t.py::test_sk[2]"]
        outcomes = [
            audit.Outcome("t.py::test_a", 0.1, False, False),
            audit.Outcome("t.py::test_sk[1]", 0.1, False, True),
            audit.Outcome("t.py::test_sk[2]", 0.1, False, True),
        ]

        duplicates, no_arcs = audit.analyse_coverage(data, nodeids, outcomes)

        assert duplicates == []
        assert no_arcs == []

    def test_a_case_that_skips_keeps_its_passing_siblings_in(self, tmp_path):
        data = _data(
            tmp_path,
            {"t.py::test_a": {MOD: [(1, 2)]}, "t.py::test_b": {MOD: [(1, 2), (2, 3)]}},
        )
        nodeids = ["t.py::test_a[1]", "t.py::test_a[2]", "t.py::test_b"]
        outcomes = [
            audit.Outcome("t.py::test_a[1]", 0.1, False, False),
            audit.Outcome("t.py::test_a[2]", 0.1, False, True),
            audit.Outcome("t.py::test_b", 0.1, False, False),
        ]

        duplicates, _ = audit.analyse_coverage(data, nodeids, outcomes)

        assert [(d.test, d.covered_by) for d in duplicates] == [
            ("t.py::test_a", "t.py::test_b")
        ]

    def test_duplicates_group_by_top_level_folder(self):
        duplicates = [
            audit.Duplicate("tests/entity/fields/test_x.py::test_a", "b", 1, 2),
            audit.Duplicate("tests/test_root.py::test_a", "b", 1, 2),
        ]

        groups = audit.group_by_dir(duplicates)

        assert list(groups) == ["tests", "tests/entity"]

    def test_function_id_strips_parameters(self):
        assert (
            audit.function_id("tests/a/test_b.py::TestC::test_d[x-1]")
            == "tests/a/test_b.py::TestC::test_d"
        )

    def test_junit_key_matches_pytest(self):
        assert audit.junit_key("tests/a/test_b.py::TestC::test_d[p.y]") == (
            "tests.a.test_b.TestC",
            "test_d[p.y]",
        )


_HELPER = """\
def one():
    return 1


def two():
    return 2


def three():
    return 3


def four():
    return 4
"""

_TESTS = """\
import subprocess
import sys

from hypothesis import given, settings, strategies as st

import helper


@pytest.fixture
def test_value():
    return helper.one()


def test_plain(test_value):
    assert test_value == 1


@settings(max_examples=2, database=None)
@given(st.integers())
def test_given(_x):
    helper.two()


class TestBox:
    def test_method(self):
        helper.three()


def test_child():
    subprocess.run([sys.executable, "-c", "import helper; helper.four()"], check=True)
"""


class TestContextHook:
    """The plugin names each test's context by its function ID, so a
    Hypothesis test, a fixture whose name starts with ``test`` and a child
    process all land where the analysis expects."""

    def test_a_real_coverage_run_records_one_context_per_test(self, tmp_path):
        # Only the helper folder is measured, so each test's arcs are the
        # helper lines it ran.
        lib = tmp_path / "lib"
        lib.mkdir()
        (lib / "helper.py").write_text(_HELPER, encoding="utf-8")
        (tmp_path / "test_x.py").write_text(
            "import pytest\n" + _TESTS, encoding="utf-8"
        )
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        data_file = tmp_path / "out" / ".coverage"
        data_file.parent.mkdir()
        rc = tomllib.loads(audit.coverage_rc(REPO / "pyproject.toml", data_file))
        run = rc["tool"]["coverage"]["run"]
        run["source"] = [str(lib)]
        run.pop("omit", None)
        rcfile = tmp_path / "out" / "rc.toml"
        rcfile.write_text(audit._toml_table("tool.coverage.run", run), encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO), str(lib)])}
        env.pop("COVERAGE_PROCESS_START", None)
        env.pop("COVERAGE_PROCESS_CONFIG", None)
        coverage = [sys.executable, "-m", "coverage"]

        completed = subprocess.run(
            [
                *coverage,
                *("run", "--rcfile", str(rcfile), "-m", "pytest"),
                *("-c", "pytest.ini", "-p", audit.PLUGIN, "-p", "no:cacheprovider"),
                *("-p", "no:randomly", "-q", "test_x.py"),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        subprocess.run(
            [*coverage, "combine", "--rcfile", str(rcfile)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            check=True,
        )
        data = CoverageData(basename=str(data_file))
        data.read()

        tests = [
            "test_x.py::test_plain",
            "test_x.py::test_given",
            "test_x.py::TestBox::test_method",
            "test_x.py::test_child",
        ]
        # ``test_plain`` and ``test_child`` run no helper line in their own
        # body, so they record no context.
        assert set(data.measured_contexts()) == {"", tests[1], tests[2]}
        helper = str(lib / "helper.py")
        data.set_query_context("test_x.py::test_given")
        assert 6 in (data.lines(helper) or [])
        data.set_query_context("test_x.py::TestBox::test_method")
        assert 10 in (data.lines(helper) or [])
        # The fixture ran ``one`` and the child process ran ``four``; both
        # went to the empty context, which the analysis drops.
        data.set_query_context("")
        assert {2, 14} <= set(data.lines(helper) or [])
        data.set_query_contexts(None)
        arcsets = audit.load_arcsets(data, tests)
        assert arcsets["test_x.py::test_given"]
        assert "test_x.py::test_plain" not in arcsets
        assert "test_x.py::test_child" not in arcsets


class TestCoverageRc:
    def test_repeats_the_run_section_and_sets_the_core(self, tmp_path):
        data_file = tmp_path / ".test-audit" / ".coverage"
        pyproject = REPO / "pyproject.toml"

        rc = tomllib.loads(audit.coverage_rc(pyproject, data_file))

        source = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"][
            "coverage"
        ]
        run = rc["tool"]["coverage"]["run"]
        assert run.pop("core") == "ctrace"
        assert run.pop("data_file") == str(data_file)
        assert run == source["run"]
        assert rc["tool"]["coverage"]["paths"] == source["paths"]

    def test_keys_and_values_outside_plain_ascii_survive(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.coverage.run]\n"
            'dynamic_context = "test_function"\n'
            "[tool.coverage.paths]\n"
            '"a.b c" = ["src/\U0001f600"]\n',
            encoding="utf-8",
        )

        rc = tomllib.loads(audit.coverage_rc(pyproject, tmp_path / ".coverage"))

        assert rc["tool"]["coverage"]["paths"] == {"a.b c": ["src/\U0001f600"]}
        assert "dynamic_context" not in rc["tool"]["coverage"]["run"]


def _private(source: str) -> list[str]:
    return [f.detail for f in audit.scan_private_state("tests/t.py", source)]


class TestPrivateStateScan:
    def test_new_on_the_same_class_is_flagged(self):
        assert _private("c = Caches.__new__(Caches)\n") == ["Caches.__new__(Caches)"]

    def test_new_on_another_class_is_not_flagged(self):
        assert _private("c = Caches.__new__(Other)\n") == []

    def test_assigning_a_private_attribute_is_flagged(self):
        assert _private("obj._caches = None\n") == ["obj._caches = ..."]

    def test_a_test_class_setting_its_own_state_is_not_flagged(self):
        source = (
            "class TestX:\n    def setup_method(self):\n"
            "        self._items = []\n"
            '        setattr(self, "_more", [])\n'
        )

        assert _private(source) == []

    def test_self_outside_a_class_is_flagged(self):
        assert _private("def helper(self):\n    self._items = []\n") == [
            "self._items = ..."
        ]

    def test_a_mock_the_function_created_is_not_flagged(self):
        source = (
            "def make():\n    cls = MagicMock()\n    cls._handlers = {}\n"
            "    m: Mock = Mock()\n    m._x = 1\n"
        )

        assert _private(source) == []

    def test_a_mock_from_another_function_is_flagged(self):
        source = (
            "def make():\n    cls = MagicMock()\n"
            "def other(cls):\n    cls._handlers = {}\n"
        )

        assert _private(source) == ["cls._handlers = ..."]

    def test_a_public_or_dunder_attribute_is_not_flagged(self):
        assert _private("obj.items = []\nobj.__dict__ = {}\n") == []

    @pytest.mark.parametrize(
        "source, detail",
        [
            ('patch.object(x, "_load")', 'patch.object(..., "_load")'),
            ('patch.object(x, attribute="_load")', 'patch.object(..., "_load")'),
            (
                'mocker.patch("protean.utils._cache")',
                'mocker.patch("protean.utils._cache")',
            ),
            ('patch(target="m._x")', 'patch("m._x")'),
            (
                'unittest.mock.patch("m._x")',
                'unittest.mock.patch("m._x")',
            ),
            (
                'monkeypatch.setattr(x, "_hook", None)',
                'monkeypatch.setattr(..., "_hook")',
            ),
            (
                'monkeypatch.setattr("protean.utils._cache", "v")',
                'monkeypatch.setattr("protean.utils._cache")',
            ),
            ('setattr(obj, "_x", 1)', 'setattr(..., "_x")'),
        ],
    )
    def test_patching_a_private_name_is_flagged(self, source, detail):
        assert _private(source + "\n") == [detail]

    @pytest.mark.parametrize(
        "source",
        [
            'patch.object(x, "load")',
            'patch("protean.utils.cache")',
            'monkeypatch.setattr("protean.utils.cache", "_v")',
            'setattr(obj, "x", 1)',
        ],
    )
    def test_patching_a_public_name_is_not_flagged(self, source):
        assert _private(source + "\n") == []


def _named(path: str, source: str) -> list[tuple[str, str]]:
    return [(f.kind, f.detail) for f in audit.scan_coverage_named(path, source)]


class TestCoverageNamedScan:
    def test_a_coverage_claim_in_a_docstring_is_flagged(self):
        source = 'def test_x():\n    """Tests to increase coverage."""\n'

        assert _named("tests/t.py", source) == [("docstring", "to increase coverage")]

    def test_a_coverage_claim_in_a_comment_is_flagged(self):
        assert _named("tests/t.py", "x = 1  # covers the uncovered lines\n") == [
            ("comment", "uncovered lines")
        ]

    def test_the_bare_word_coverage_is_not_flagged(self):
        source = '"""Tests of the coverage lane."""\n# run coverage\n'

        assert _named("tests/t.py", source) == []

    def test_a_coverage_file_name_is_flagged(self):
        assert _named("tests/foo_coverage.py", "") == [("file name", "foo_coverage.py")]


def _write(root: Path, path: str, source: str, encoding: str = "utf-8") -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(source, encoding=encoding)


class TestStaticScan:
    def test_a_tree_scan_skips_excluded_files_and_the_support_folder(self, tmp_path):
        claim = '"""Tests for coverage."""\nobj._x = 1\n'
        _write(tmp_path, "tests/test_guards.py", '"""Explicit test coverage."""\n')
        _write(tmp_path, "tests/pm/test_coverage.py", "")
        _write(tmp_path, "tests/test_bom.py", "obj._y = 1\n", encoding="utf-8-sig")
        for path in audit.EXCLUDED:
            _write(tmp_path, path, claim)
        _write(tmp_path, "tests/support/helper.py", claim)

        private, coverage_named = audit.static_scan(tmp_path)

        assert [(f.path, f.detail) for f in private] == [
            ("tests/test_bom.py", "obj._y = ...")
        ]
        assert [(f.path, f.kind) for f in coverage_named] == [
            ("tests/pm/test_coverage.py", "file name"),
            ("tests/test_guards.py", "docstring"),
        ]

    def test_a_file_that_does_not_parse_stops_the_scan(self, tmp_path):
        _write(tmp_path, "tests/test_broken.py", "def broken(:\n")

        with pytest.raises(audit.StageError, match="tests/test_broken.py"):
            audit.static_scan(tmp_path)

    def test_every_file_in_the_repo_parses(self):
        private, coverage_named = audit.static_scan(REPO)

        assert private and coverage_named
        paths = {f.path for f in private + coverage_named}
        assert paths.isdisjoint(audit.EXCLUDED)


class TestOrderDependence:
    def test_each_rerun_result_has_its_own_list(self):
        results = {"t::flaky": "passed", "t::broken": "failed", "t::guard": "skipped"}

        order_dependent, plain, skipped = audit.classify_failures(
            results, results.__getitem__
        )

        assert order_dependent == ["t::flaky"]
        assert plain == ["t::broken"]
        assert skipped == ["t::guard"]

    def test_a_test_that_failed_in_default_order_is_a_plain_failure(self):
        rerun: list[str] = []

        def rerun_alone(nodeid: str) -> str:
            rerun.append(nodeid)
            return "passed"

        order_dependent, plain, skipped = audit.classify_failures(
            ["t::a", "t::b"], rerun_alone, failed_in_default_order=["t::b"]
        )

        assert order_dependent == ["t::a"]
        assert plain == ["t::b"]
        assert skipped == []
        assert rerun == ["t::a"]

    def test_no_failures_means_nothing_to_classify(self):
        assert audit.classify_failures([], lambda nodeid: "passed") == ([], [], [])

    @pytest.mark.parametrize(
        ("failed", "skipped", "result"),
        [(False, False, "passed"), (True, False, "failed"), (False, True, "skipped")],
    )
    def test_a_rerun_result_comes_from_the_test_outcome(self, failed, skipped, result):
        outcomes = [
            audit.Outcome("t::other", 0.1, True, False),
            audit.Outcome("t::a", 0.1, failed, skipped),
        ]

        assert audit.rerun_result(outcomes, "t::a") == result

    def test_a_rerun_without_the_test_stops_the_stage(self):
        outcomes = [audit.Outcome("t::other", 0.1, False, False)]

        with pytest.raises(audit.StageError, match="no result for it"):
            audit.rerun_result(outcomes, "t::a")

    def test_junit_outcomes_map_back_to_node_ids(self, tmp_path):
        xml = tmp_path / "run.xml"
        xml.write_text(
            "<testsuites><testsuite>"
            '<testcase classname="tests.a.test_b.TestC" name="test_d[1]" time="2.5">'
            "<failure/></testcase>"
            '<testcase classname="tests.a.test_b" name="test_e" time="0.1">'
            "<skipped/></testcase>"
            '<testcase classname="tests.a.test_b" name="test_f" time="0.2">'
            "<error/></testcase>"
            '<testcase classname="tests.a.test_b" name="test_g" time="0.3">'
            '<skipped type="pytest.xfail" message=""/></testcase>'
            "</testsuite></testsuites>",
            encoding="utf-8",
        )
        nodeids = [
            "tests/a/test_b.py::TestC::test_d[1]",
            "tests/a/test_b.py::test_e",
            "tests/a/test_b.py::test_f",
            "tests/a/test_b.py::test_g",
        ]

        outcomes = audit.read_junit(xml, nodeids)

        assert outcomes == [
            audit.Outcome(nodeids[0], 2.5, failed=True, skipped=False),
            audit.Outcome(nodeids[1], 0.1, failed=False, skipped=True),
            audit.Outcome(nodeids[2], 0.2, failed=True, skipped=False),
            audit.Outcome(nodeids[3], 0.3, failed=False, skipped=True, xfailed=True),
        ]

    def test_slowest_is_capped(self):
        outcomes = [audit.Outcome(f"t::{i}", float(i), False, False) for i in range(60)]

        top = audit.slowest(outcomes)

        assert len(top) == audit.SLOWEST == 50
        assert top[0].nodeid == "t::59"


def _junit(path: Path, cases: list[tuple[str, str, str]]) -> None:
    """A JUnit file of ``(node ID, time, outcome tag or "")`` cases."""
    body = ""
    for nodeid, time, tag in cases:
        classname, name = audit.junit_key(nodeid)
        inner = f"<{tag}/>" if tag else ""
        body += f'<testcase classname="{classname}" name="{name}" time="{time}">{inner}</testcase>'
    path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>")


class _Runner:
    """Records each command, and runs ``on_run`` to fake its effect."""

    def __init__(self, on_run):
        self.calls: list[tuple[list[str], Path | None]] = []
        self.on_run = on_run

    def __call__(self, cmd: list[str], log: Path | None) -> int:
        self.calls.append((cmd, log))
        return self.on_run(cmd, log)


NODES = [
    "tests/a/test_b.py::test_flaky",
    "tests/a/test_b.py::test_broken",
    "tests/a/test_b.py::test_guard",
]

# What each test does when it runs again alone: the guard skips, as the
# reclamation guards in ``tests/test_fd_hermeticity.py`` do, and pytest exits
# 0 for it all the same.
ALONE = {NODES[0]: (0, ""), NODES[1]: (1, "failure"), NODES[2]: (0, "skipped")}


def _junit_path(cmd: list[str]) -> Path:
    return Path(next(a for a in cmd if a.startswith("--junitxml=")).split("=", 1)[1])


class TestRandomStage:
    def _shuffled(
        self,
        seed_line: str,
        code: int = 1,
        rerun_code: int | None = None,
        write_rerun: bool = True,
    ):
        def on_run(cmd, log):
            if "randomly" in cmd and log is not None:
                log.write_text(f"Using {seed_line}\n", encoding="utf-8")
                _junit(
                    _junit_path(cmd),
                    [(nodeid, "1.0", "failure") for nodeid in NODES],
                )
                return code
            alone_code, tag = ALONE[cmd[-1]]
            if write_rerun:
                _junit(_junit_path(cmd), [(cmd[-1], "0.1", tag)])
            return alone_code if rerun_code is None else rerun_code

        return _Runner(on_run)

    def test_shuffles_with_the_seed_and_reruns_each_failure_alone(self, tmp_path):
        runner = self._shuffled("--randomly-seed=7")

        times, order_dependent, plain, skipped = audit.random_stage(
            7, NODES, out_dir=tmp_path, runner=runner
        )

        shuffled, log = runner.calls[0]
        assert shuffled[shuffled.index("randomly") - 1] == "-p"
        assert "--randomly-seed=7" in shuffled
        assert "no:randomly" not in shuffled
        assert log == tmp_path / "random-run.log"
        reruns = [cmd for cmd, _ in runner.calls[1:]]
        assert sorted(cmd[-1] for cmd in reruns) == sorted(NODES)
        assert all(cmd[-4:-2] == ["-p", "no:randomly"] for cmd in reruns)
        assert all(_junit_path(cmd) == tmp_path / "rerun.xml" for cmd in reruns)
        assert order_dependent == [NODES[0]]
        assert plain == [NODES[1]]
        assert skipped == [NODES[2]]
        assert sorted(o.nodeid for o in times) == sorted(NODES)

    def test_a_failure_in_default_order_is_not_rerun(self, tmp_path):
        runner = self._shuffled("--randomly-seed=7")

        _, order_dependent, plain, skipped = audit.random_stage(
            7, NODES, [NODES[0]], out_dir=tmp_path, runner=runner
        )

        assert order_dependent == []
        assert plain == sorted(NODES[:2])
        assert skipped == [NODES[2]]
        assert sorted(cmd[-1] for cmd, _ in runner.calls[1:]) == sorted(NODES[1:])

    def test_a_missing_seed_line_stops_the_stage(self, tmp_path):
        runner = self._shuffled("--randomly-seed=8")

        with pytest.raises(audit.StageError, match="pytest-randomly did not run"):
            audit.random_stage(7, NODES, out_dir=tmp_path, runner=runner)

    def test_a_run_that_could_not_start_stops_the_stage(self, tmp_path):
        runner = self._shuffled("--randomly-seed=7", code=4)

        with pytest.raises(audit.StageError, match="exited 4"):
            audit.random_stage(7, NODES, out_dir=tmp_path, runner=runner)

    def test_a_rerun_that_could_not_start_stops_the_stage(self, tmp_path):
        runner = self._shuffled("--randomly-seed=7", rerun_code=4)

        with pytest.raises(audit.StageError, match="alone exited 4"):
            audit.random_stage(7, NODES, out_dir=tmp_path, runner=runner)

    def test_a_rerun_that_wrote_no_results_stops_the_stage(self, tmp_path):
        runner = self._shuffled("--randomly-seed=7", write_rerun=False)

        with pytest.raises(audit.StageError, match="wrote no JUnit results"):
            audit.random_stage(7, NODES, out_dir=tmp_path, runner=runner)


class TestCoverageStage:
    def _runner(self, out_dir: Path, run_code: int = 1, combine: bool = True):
        def on_run(cmd, log):
            if "run" in cmd:
                junit = next(a for a in cmd if a.startswith("--junitxml="))
                _junit(
                    Path(junit.split("=", 1)[1]),
                    [
                        ("t.py::test_a", "0.1", ""),
                        ("t.py::test_b", "0.1", ""),
                        ("t.py::test_c", "0.1", "failure"),
                    ],
                )
                return run_code
            if combine:
                data = CoverageData(basename=str(out_dir / ".coverage"))
                data.set_context("t.py::test_a")
                data.add_arcs({MOD: [(1, 2)]})
                data.set_context("t.py::test_b")
                data.add_arcs({MOD: [(1, 2), (2, 3)]})
                data.write()
            return 0

        return _Runner(on_run)

    def test_runs_with_the_plugin_and_keeps_data_inside_the_audit_folder(
        self, tmp_path
    ):
        (tmp_path / ".coverage.stale").write_text("old", encoding="utf-8")
        runner = self._runner(tmp_path)

        duplicates, no_arcs, failed = audit.coverage_stage(
            ["t.py::test_a", "t.py::test_b", "t.py::test_c"],
            out_dir=tmp_path,
            runner=runner,
        )

        run_cmd = runner.calls[0][0]
        assert run_cmd[run_cmd.index(audit.PLUGIN) - 1] == "-p"
        rc_path = Path(run_cmd[run_cmd.index("--rcfile") + 1])
        rc = tomllib.loads(rc_path.read_text(encoding="utf-8"))
        assert rc["tool"]["coverage"]["run"]["data_file"] == str(tmp_path / ".coverage")
        assert not (tmp_path / ".coverage.stale").exists()
        assert duplicates == [audit.Duplicate("t.py::test_a", "t.py::test_b", 1, 2)]
        assert no_arcs == []
        assert failed == ["t.py::test_c"]

    def test_a_run_that_could_not_start_stops_the_stage(self, tmp_path):
        with pytest.raises(audit.StageError, match="exited 2"):
            audit.coverage_stage([], out_dir=tmp_path, runner=self._runner(tmp_path, 2))

    def test_no_data_stops_the_stage(self, tmp_path):
        runner = self._runner(tmp_path, combine=False)

        with pytest.raises(audit.StageError, match="wrote no data"):
            audit.coverage_stage([], out_dir=tmp_path, runner=runner)


class TestMain:
    def _stages(self, monkeypatch, tmp_path, random_stage):
        monkeypatch.setattr(audit, "OUT_DIR", tmp_path)
        finding = audit.Finding("tests/p.py", 3, "assignment", "obj._x = ...")
        monkeypatch.setattr(audit, "static_scan", lambda root: ([finding], []))
        monkeypatch.setattr(audit, "collect", lambda out: ["t.py::test_a"])
        monkeypatch.setattr(
            audit, "coverage_stage", lambda nodeids: ([], [], ["t.py::test_a"])
        )
        monkeypatch.setattr(audit, "random_stage", random_stage)

    def test_writes_both_reports_and_exits_0(self, monkeypatch, tmp_path):
        seen = {}

        def random_stage(seed, nodeids, failed):
            seen.update(seed=seed, failed=failed)
            return [], [], ["t.py::test_a"], []

        self._stages(monkeypatch, tmp_path, random_stage)

        assert audit.main(["--seed", "5"]) == 0

        assert seen == {"seed": 5, "failed": ["t.py::test_a"]}
        report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
        assert report["seed"] == 5
        assert report["plain_failures"] == ["t.py::test_a"]
        assert report["private_state"][0]["detail"] == "obj._x = ..."
        assert "--seed 5" in (tmp_path / "report.md").read_text(encoding="utf-8")

    def test_a_stage_that_could_not_run_exits_1_without_a_report(
        self, monkeypatch, tmp_path
    ):
        def random_stage(seed, nodeids, failed):
            raise audit.StageError("the random-order run exited 4")

        self._stages(monkeypatch, tmp_path, random_stage)

        assert audit.main(["--seed", "5"]) == 1

        assert not (tmp_path / "report.json").exists()
        assert not (tmp_path / "report.md").exists()


def _section(markdown: str, heading: str) -> str:
    """The text under ``heading`` up to the next heading of the same level."""
    level = heading.split(" ", 1)[0]
    rest = markdown.split(heading + "\n", 1)[1]
    for line in rest.splitlines():
        if line.startswith("#") and line.split(" ", 1)[0] in {
            level,
            "#" * (len(level) - 1),
        }:
            return rest.split("\n" + line + "\n", 1)[0]
    return rest


def _report(**overrides):
    fields = {
        "seed": 1234,
        "duplicates": [],
        "no_arcs": [],
        "private_state": [],
        "coverage_named": [],
        "slowest": [],
        "order_dependent": [],
        "plain_failures": [],
        "skipped_alone": [],
    }
    return audit.Report(**{**fields, **overrides})


def _full_report():
    return _report(
        duplicates=[
            audit.Duplicate(
                "tests/e/test_a.py::test_a", "tests/e/test_a.py::test_b", 1, 2
            )
        ],
        no_arcs=["tests/e/test_a.py::test_none"],
        private_state=[audit.Finding("tests/p.py", 3, "assignment", "obj._x = ...")],
        coverage_named=[
            audit.Finding("tests/c_coverage.py", 1, "file name", "c_coverage.py")
        ],
        slowest=[audit.Outcome("tests/s.py::test_slow", 9.5, False, False)],
        order_dependent=["tests/o.py::test_flaky"],
        plain_failures=["tests/o.py::test_broken"],
        skipped_alone=["tests/o.py::test_guard"],
    )


class TestReport:
    def test_every_item_sits_under_its_own_heading(self):
        markdown = audit.render_markdown(_full_report())

        assert "deletes no test" in markdown
        duplicates = _section(markdown, "## Duplicate candidates")
        assert "### `tests/e`" in duplicates
        assert "- `tests/e/test_a.py::test_a` (1 arcs) is covered by" in duplicates
        no_arcs = _section(markdown, "### Tests with no covered arcs of their own")
        assert "- `tests/e/test_a.py::test_none`" in no_arcs
        private = _section(markdown, "### Private state")
        assert "line 3, assignment: `obj._x = ...`" in private
        assert "c_coverage.py" not in private
        named = _section(markdown, "### Coverage-named")
        assert "line 1, file name: `c_coverage.py`" in named
        for path in audit.EXCLUDED:
            assert f"- `{path}`: {audit.EXCLUDED[path]}" in named
        slow = _section(markdown, "## The 50 slowest tests")
        assert "1. `tests/s.py::test_slow`: 9.50s" in slow
        order = _section(markdown, "## Order-dependent tests")
        assert "--seed 1234" in order
        passed_alone, rest = order.split("failed again alone", 1)
        failed_again, skipped_alone = rest.split("skipped or xfailed", 1)
        assert "- `tests/o.py::test_flaky`" in passed_alone
        assert "test_broken" not in passed_alone
        assert "- `tests/o.py::test_broken`" in failed_again
        assert "test_flaky" not in failed_again
        assert "test_guard" not in passed_alone + failed_again
        assert "- `tests/o.py::test_guard`" in skipped_alone

    def test_empty_sections_say_none(self):
        markdown = audit.render_markdown(_report())

        sections = markdown.split("\n## ")[1:]
        assert len(sections) == 4
        assert all("None." in section for section in sections)

    def test_json_keeps_every_field_under_its_key(self):
        data = _full_report().to_json()

        assert data["seed"] == 1234
        assert (
            data["duplicates"]["tests/e"][0]["covered_by"]
            == "tests/e/test_a.py::test_b"
        )
        assert data["no_arcs"] == ["tests/e/test_a.py::test_none"]
        assert data["private_state"][0]["detail"] == "obj._x = ..."
        assert data["coverage_named"][0]["path"] == "tests/c_coverage.py"
        assert data["excluded"] == audit.EXCLUDED
        assert data["slowest"] == [{"test": "tests/s.py::test_slow", "seconds": 9.5}]
        assert data["order_dependent"] == ["tests/o.py::test_flaky"]
        assert data["plain_failures"] == ["tests/o.py::test_broken"]
        assert data["skipped_alone"] == ["tests/o.py::test_guard"]


# Child pytest commands that read the repo's own config, whose ``addopts``
# already turns pytest-randomly off, and lists that are not commands.
_READS_REPO_ADDOPTS = {
    ("tests/cli/test_test.py", "--version"): "an expected command, not one that runs",
    ("tests/cli/test_test.py", "--collect-only"): "runs in the repo root",
}


class TestChildPytestCommands:
    """A child pytest that does not read the repo's ``addopts`` passes
    ``-p no:randomly``, so pytest-randomly does not shuffle it."""

    def test_every_child_pytest_command_turns_randomly_off(self):
        commands = []
        for file in sorted((REPO / "tests").rglob("*.py")):
            path = file.relative_to(REPO).as_posix()
            for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.List):
                    continue
                values = [
                    e.value if isinstance(e, ast.Constant) else None for e in node.elts
                ]
                if ("-m", "pytest") in itertools.pairwise(values):
                    commands.append((path, node.lineno, values))

        assert commands
        missing = [
            (path, line)
            for path, line, values in commands
            if "no:randomly" not in values
            and not any((path, v) in _READS_REPO_ADDOPTS for v in values)
        ]
        assert missing == []
