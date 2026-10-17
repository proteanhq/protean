"""`scripts/test_audit.py`, the script behind `make test-audit`.

The full audit runs the whole core suite several times, so these tests check
its parts on small inputs: the subset search on hand-built coverage data, the
context names it matches against, the static scan, and the order-dependence
check with a stubbed re-run.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
from coverage import CoverageData
from coverage.context import qualname_from_frame
from hypothesis import given, settings
from hypothesis import strategies as st

REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "test_audit_script", REPO / "scripts" / "test_audit.py"
)
assert _spec is not None and _spec.loader is not None
audit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = audit
_spec.loader.exec_module(audit)

pytestmark = pytest.mark.no_test_domain


def _data(tmp_path: Path, arcs: dict[str, list[tuple[int, int]]]) -> CoverageData:
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    for context, context_arcs in arcs.items():
        data.set_context(context)
        if context_arcs:
            data.add_arcs({"/src/protean/mod.py": context_arcs})
    data.write()
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.read()
    return data


class TestSubsetSearch:
    def test_a_subset_is_reported_with_its_covering_test(self, tmp_path):
        data = _data(
            tmp_path,
            {
                "m.test_a": [(1, 2), (2, 3)],
                "m.test_b": [(1, 2), (2, 3), (3, 4)],
                "m.test_c": [(2, 3), (3, 4), (5, 6)],
            },
        )
        labels = {f"m.test_{x}": f"tests/t/test_m.py::test_{x}" for x in "abc"}

        duplicates = audit.find_duplicates(audit.load_arcsets(data, labels))

        assert duplicates == [
            audit.Duplicate(
                test="tests/t/test_m.py::test_a",
                covered_by="tests/t/test_m.py::test_b",
                arcs=2,
                covering_arcs=3,
            )
        ]

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
                "": [(1, 2), (2, 3), (3, 4)],
                "tests.conftest.test_domain": [(1, 2), (2, 3), (3, 4)],
                "m.test_a": [(1, 2)],
            },
        )
        labels = {"m.test_a": "tests/t/test_m.py::test_a"}

        arcsets = audit.load_arcsets(data, labels)

        assert list(arcsets) == ["tests/t/test_m.py::test_a"]
        assert audit.find_duplicates(arcsets) == []

    def test_parametrized_cases_share_one_label(self, tmp_path):
        data = _data(tmp_path, {"m.test_a": [(1, 2)], "m.test_b": [(1, 2), (2, 3)]})
        labels = {
            "m.test_a": audit.function_id("tests/t/test_m.py::test_a[1-x]"),
            "m.test_b": "tests/t/test_m.py::test_b",
        }

        duplicates = audit.find_duplicates(audit.load_arcsets(data, labels))

        assert [d.test for d in duplicates] == ["tests/t/test_m.py::test_a"]

    def test_a_test_that_ran_with_no_arcs_is_listed_apart(self, tmp_path):
        data = _data(tmp_path, {"m.test_a": [(1, 2)]})
        collected = [
            ("tests/t/test_m.py::test_a", "m.test_a"),
            ("tests/t/test_m.py::test_empty[1]", "m.test_empty"),
            ("tests/t/test_m.py::test_skipped", "m.test_skipped"),
        ]
        outcomes = [
            audit.Outcome("tests/t/test_m.py::test_a", 0.1, False, False),
            audit.Outcome("tests/t/test_m.py::test_empty[1]", 0.1, False, False),
            audit.Outcome("tests/t/test_m.py::test_skipped", 0.0, False, True),
        ]

        duplicates, no_arcs = audit.analyse_coverage(data, collected, outcomes)

        assert duplicates == []
        assert no_arcs == ["tests/t/test_m.py::test_empty"]

    def test_tests_sharing_a_context_report_as_the_first_node(self, tmp_path):
        data = _data(
            tmp_path, {"m.Base.test_a": [(1, 2)], "m.test_b": [(1, 2), (2, 3)]}
        )
        collected = [
            ("tests/t/test_m.py::TestZ::test_a", "m.Base.test_a"),
            ("tests/t/test_m.py::TestY::test_a", "m.Base.test_a"),
            ("tests/t/test_m.py::test_b", "m.test_b"),
        ]

        duplicates, _ = audit.analyse_coverage(data, collected, [])

        assert [(d.test, d.covered_by) for d in duplicates] == [
            ("tests/t/test_m.py::TestY::test_a", "tests/t/test_m.py::test_b")
        ]

    def test_duplicates_group_by_top_level_folder(self):
        duplicates = [
            audit.Duplicate("tests/entity/fields/test_x.py::test_a", "b", 1, 2),
            audit.Duplicate("tests/test_root.py::test_a", "b", 1, 2),
        ]

        groups = audit.group_by_dir(duplicates)

        assert list(groups) == ["tests", "tests/entity"]


def check_function():
    return sys._getframe()


class Base:
    def check_method(self):
        return sys._getframe()


class Child(Base):
    pass


_frames: list[object] = []


@patch("os.getcwd")
def check_patched(_getcwd):
    _frames.append(sys._getframe())


@settings(max_examples=1, database=None)
@given(st.just(1))
def check_given(_value):
    _frames.append(sys._getframe())


class TestContextNames:
    """The names `context_key` computes are the ones coverage.py records."""

    def test_a_module_function(self):
        assert audit.context_key(check_function, bound=False) == qualname_from_frame(
            check_function()
        )

    def test_a_method(self):
        instance = Base()

        assert audit.context_key(
            instance.check_method, bound=True
        ) == qualname_from_frame(instance.check_method())

    def test_an_inherited_method_takes_the_defining_class(self):
        instance = Child()

        key = audit.context_key(instance.check_method, bound=True)

        assert key == qualname_from_frame(instance.check_method())
        assert key.endswith(".Base.check_method")

    @pytest.mark.parametrize("func", [check_patched, check_given])
    def test_a_decorated_function_takes_the_inner_frame(self, func):
        _frames.clear()
        func()

        key = audit.context_key(func, bound=False)

        assert _frames
        assert key == qualname_from_frame(_frames[-1])
        assert key == f"{__name__}.{func.__name__}"

    def test_a_nested_function_has_no_context(self):
        def check_nested():
            return sys._getframe()

        assert audit.context_key(check_nested, bound=False) is None
        assert qualname_from_frame(check_nested()) is None

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


class TestCoverageRc:
    def test_repeats_the_run_section_and_adds_the_context(self, tmp_path):
        data_file = tmp_path / ".test-audit" / ".coverage"
        pyproject = REPO / "pyproject.toml"

        rc = tomllib.loads(audit.coverage_rc(pyproject, data_file))

        source = tomllib.loads(pyproject.read_text(encoding="utf-8"))["tool"][
            "coverage"
        ]
        run = rc["tool"]["coverage"]["run"]
        assert run.pop("dynamic_context") == "test_function"
        assert run.pop("data_file") == str(data_file)
        assert run == source["run"]
        assert rc["tool"]["coverage"]["paths"] == source["paths"]


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
        source = "class TestX:\n    def setup_method(self):\n        self._items = []\n"

        assert _private(source) == []

    def test_self_outside_a_class_is_flagged(self):
        assert _private("def helper(self):\n    self._items = []\n") == [
            "self._items = ..."
        ]

    def test_a_mock_the_function_created_is_not_flagged(self):
        source = "def make():\n    cls = MagicMock()\n    cls._handlers = {}\n"

        assert _private(source) == []

    def test_a_mock_from_another_function_is_flagged(self):
        source = (
            "def make():\n    cls = MagicMock()\n"
            "def other(cls):\n    cls._handlers = {}\n"
        )

        assert _private(source) == ["cls._handlers = ..."]

    def test_a_public_or_dunder_attribute_is_not_flagged(self):
        assert _private("obj.items = []\nobj.__dict__ = {}\n") == []

    def test_patching_a_private_name_is_flagged(self):
        source = (
            'patch.object(x, "_load")\n'
            'mocker.patch("protean.utils._cache")\n'
            'monkeypatch.setattr(x, "_hook", None)\n'
        )

        assert len(_private(source)) == 3

    def test_patching_a_public_name_is_not_flagged(self):
        source = 'patch.object(x, "load")\npatch("protean.utils.cache")\n'

        assert _private(source) == []


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
        source = '"""Tests for the coverage lane."""\n# run coverage\n'

        assert _named("tests/t.py", source) == []

    def test_a_coverage_file_name_is_flagged(self):
        assert _named("tests/foo_coverage.py", "") == [("file name", "foo_coverage.py")]

    def test_the_repo_scan_skips_excluded_files_and_finds_the_guards(self):
        private, coverage_named = audit.static_scan(REPO)

        paths = {f.path for f in private + coverage_named}
        assert "tests/test_coverage_guards.py" in paths
        assert "tests/process_manager/test_coverage.py" in paths
        assert paths.isdisjoint(audit.EXCLUDED)
        assert not any(path.startswith("tests/support/") for path in paths)


class TestOrderDependence:
    def test_a_test_that_passes_alone_is_order_dependent(self):
        order_dependent, plain = audit.classify_failures(
            ["t::flaky", "t::broken"], lambda nodeid: nodeid == "t::flaky"
        )

        assert order_dependent == ["t::flaky"]
        assert plain == ["t::broken"]

    def test_no_failures_means_nothing_to_classify(self):
        assert audit.classify_failures([], lambda nodeid: True) == ([], [])

    def test_junit_outcomes_map_back_to_node_ids(self, tmp_path):
        xml = tmp_path / "run.xml"
        xml.write_text(
            "<testsuites><testsuite>"
            '<testcase classname="tests.a.test_b.TestC" name="test_d[1]" time="2.5">'
            "<failure/></testcase>"
            '<testcase classname="tests.a.test_b" name="test_e" time="0.1">'
            "<skipped/></testcase>"
            "</testsuite></testsuites>",
            encoding="utf-8",
        )
        nodeids = ["tests/a/test_b.py::TestC::test_d[1]", "tests/a/test_b.py::test_e"]

        outcomes = audit.read_junit(xml, nodeids)

        assert outcomes == [
            audit.Outcome(nodeids[0], 2.5, failed=True, skipped=False),
            audit.Outcome(nodeids[1], 0.1, failed=False, skipped=True),
        ]

    def test_slowest_is_capped(self):
        outcomes = [audit.Outcome(f"t::{i}", float(i), False, False) for i in range(60)]

        top = audit.slowest(outcomes)

        assert len(top) == audit.SLOWEST == 50
        assert top[0].nodeid == "t::59"


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
    }
    return audit.Report(**{**fields, **overrides})


class TestReport:
    def test_the_four_sections_and_the_seed(self):
        markdown = audit.render_markdown(
            _report(
                duplicates=[audit.Duplicate("tests/e/test_a.py::test_a", "b", 1, 2)],
                order_dependent=["tests/e/test_a.py::test_flaky"],
            )
        )

        for heading in (
            "## Duplicate candidates",
            "## Private-state and coverage-named tests",
            "## The 50 slowest tests",
            "## Order-dependent tests",
        ):
            assert heading in markdown
        assert "### `tests/e`" in markdown
        assert "--seed 1234" in markdown
        assert "- `tests/e/test_a.py::test_flaky`" in markdown
        assert "deletes nothing" in markdown

    def test_empty_sections_say_none(self):
        markdown = audit.render_markdown(_report())

        sections = markdown.split("\n## ")[1:]
        assert len(sections) == 4
        assert all("None." in section for section in sections)

    def test_json_groups_duplicates_and_keeps_the_seed(self):
        report = _report(
            duplicates=[audit.Duplicate("tests/e/test_a.py::test_a", "b", 1, 2)]
        )

        data = report.to_json()

        assert data["seed"] == 1234
        assert list(data["duplicates"]) == ["tests/e"]
        assert data["duplicates"]["tests/e"][0]["covered_by"] == "b"
