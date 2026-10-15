"""Run the examples on ``docs/patterns/testing-event-driven-flows.md``."""

import pytest

from tests.docs.support import DOCS_SRC, outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain

FOLDER = DOCS_SRC / "patterns" / "testing-event-driven-flows"


def _assert_passed(result, count):
    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": count}


def test_level_1_domain_unit_tests_pass():
    _assert_passed(
        run_example_tests(
            "patterns/testing-event-driven-flows/test_order_placement.py"
        ),
        2,
    )


def test_level_2_sync_flow_tests_pass():
    _assert_passed(
        run_example_tests(
            "patterns/testing-event-driven-flows/test_order_flow_sync.py"
        ),
        2,
    )


def test_level_3_async_and_priority_lane_tests_pass():
    _assert_passed(
        run_example_tests(
            "patterns/testing-event-driven-flows/test_order_flow_async.py"
        ),
        2,
    )


def test_error_handling_test_passes():
    _assert_passed(
        run_example_tests("patterns/testing-event-driven-flows/test_error_handling.py"),
        1,
    )


def test_all_example_files_pass_in_one_session():
    # A reader runs the whole tests folder at once, so a handler one file
    # registers must not reach the tests in the others.
    others = [
        str(FOLDER / name)
        for name in (
            "test_order_flow_sync.py",
            "test_order_flow_async.py",
            "test_error_handling.py",
        )
    ]
    _assert_passed(
        run_example_tests(
            "patterns/testing-event-driven-flows/test_order_placement.py",
            args=others,
        ),
        7,
    )
