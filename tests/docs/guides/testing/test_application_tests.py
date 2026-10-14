"""The BDD examples on ``docs/guides/testing/application-tests.md`` pass under pytest-bdd.

Each step file runs with the conftests above it: the root ``conftest.py`` that
initializes the ``myapp`` domain with sync processing, the shared
``the domain is initialized`` step with the marker registration for the
Gherkin tags, and the ordering steps. Every scenario in the feature files must
pass, and each tag selection the page lists must pick the tagged scenarios.
"""

import re

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
        "guides/testing/application-tests/bdd/ordering/test_place_order.py",
        args=["-W", "error::pytest.PytestUnknownMarkWarning"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 6}


@pytest.mark.parametrize(
    "selection, expected",
    [
        pytest.param("ordering", 6, id="ordering"),
        pytest.param("smoke", 6, id="smoke"),
        pytest.param(
            "happy_path and not validation",
            ["test_placing_an_order_updates_inventory"],
            id="happy-path",
        ),
        pytest.param(
            "validation",
            ["test_cannot_order_more_than_available_stock"],
            id="validation",
        ),
    ],
)
def test_the_tag_selections_on_the_page_pick_the_tagged_scenarios(selection, expected):
    result = run_example_tests(
        "guides/testing/application-tests/bdd/ordering/test_place_order.py",
        args=["-m", selection, "--strict-markers", "-v"],
    )

    passed = re.findall(r"::(\S+) PASSED", result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
    if isinstance(expected, int):
        assert len(passed) == expected
    else:
        assert passed == expected
