"""The BDD examples on ``docs/guides/testing/application-tests.md`` pass under pytest-bdd.

Each step file runs with the conftests above it: the root ``conftest.py`` that
initializes the ``myapp`` domain with sync processing, the shared
``the domain is initialized`` step, and the ordering steps. Every scenario in
the feature files must pass.
"""

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def test_the_registration_scenarios_pass():
    result = run_example_tests(
        "guides/testing/application-tests/bdd/registration/test_register_user.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 3}


def test_the_application_service_scenarios_pass():
    result = run_example_tests(
        "guides/testing/application-tests/bdd/registration/test_activate_user.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 2}


def test_the_ordering_scenarios_and_outline_pass():
    result = run_example_tests(
        "guides/testing/application-tests/bdd/ordering/test_place_order.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 6}
