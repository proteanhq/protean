"""The examples on ``docs/guides/testing/fixtures-and-patterns.md`` pass under pytest.

The page's BDD steps come from the application-tests folder, and
``test_application_tests.py`` runs them.
"""

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def test_the_conftest_and_clock_examples_pass():
    result = run_example_tests("guides/testing/fixtures-and-patterns/001.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 5}


def test_the_integration_ready_conftest_defaults_to_memory():
    result = run_example_tests(
        "guides/testing/fixtures-and-patterns/002.py", env={"TEST_DB": "memory"}
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 3}


def test_the_integration_ready_conftest_switches_to_sqlite():
    result = run_example_tests(
        "guides/testing/fixtures-and-patterns/002.py", env={"TEST_DB": "sqlite"}
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 3}


def test_the_manual_cleanup_resets_data_between_tests():
    result = run_example_tests("guides/testing/fixtures-and-patterns/003.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 2}
