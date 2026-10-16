"""Run the examples on ``docs/patterns/testing-domain-logic-in-isolation.md``."""

import pytest

from tests.docs.support import DOCS_SRC, outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain

FOLDER = DOCS_SRC / "patterns" / "testing-domain-logic-in-isolation"


def _assert_passed(result, count):
    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": count}


def test_aggregate_tests_pass():
    _assert_passed(
        run_example_tests(
            "patterns/testing-domain-logic-in-isolation/test_aggregates.py"
        ),
        10,
    )


def test_value_object_tests_pass():
    _assert_passed(
        run_example_tests(
            "patterns/testing-domain-logic-in-isolation/test_value_objects.py"
        ),
        13,
    )


def test_invariant_tests_pass():
    _assert_passed(
        run_example_tests(
            "patterns/testing-domain-logic-in-isolation/test_invariants.py"
        ),
        4,
    )


def test_domain_service_tests_pass():
    _assert_passed(
        run_example_tests(
            "patterns/testing-domain-logic-in-isolation/test_domain_services.py"
        ),
        3,
    )


def test_entity_tests_pass():
    _assert_passed(
        run_example_tests(
            "patterns/testing-domain-logic-in-isolation/test_entities.py"
        ),
        3,
    )


def test_integration_tests_pass():
    _assert_passed(
        run_example_tests(
            "patterns/testing-domain-logic-in-isolation/test_integration.py"
        ),
        3,
    )


def test_all_example_files_pass_in_one_session():
    # A reader runs the whole tests folder at once, so data one file stores
    # must not reach the tests in the others.
    others = [
        str(FOLDER / name)
        for name in (
            "test_value_objects.py",
            "test_invariants.py",
            "test_domain_services.py",
            "test_entities.py",
            "test_integration.py",
        )
    ]
    _assert_passed(
        run_example_tests(
            "patterns/testing-domain-logic-in-isolation/test_aggregates.py",
            args=others,
        ),
        36,
    )
