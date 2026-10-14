"""The examples on ``docs/guides/testing/fixtures-and-patterns.md`` pass under pytest.

Each example folder holds the ``conftest.py`` the page shows and a test module
that uses its fixtures. The page's BDD steps come from the application-tests
folder, and ``test_application_tests.py`` runs them.
"""

import pytest

from tests.docs.support import outcome_counts, run_example_tests
from tests.shared import POSTGRES_URI

pytestmark = pytest.mark.no_test_domain


def test_the_minimal_conftest_and_clock_examples_pass():
    result = run_example_tests(
        "guides/testing/fixtures-and-patterns/minimal/test_patterns.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 6}


# A bare "sqlite" id would become a keyword, and the suite's conftest skips a
# test with that keyword unless --sqlite is given. SQLite needs no service.
@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="default-memory"),
        pytest.param({"TEST_DB": "sqlite"}, id="sqlite-adapter"),
        pytest.param(
            {"TEST_DB": "postgresql", "DATABASE_URL": POSTGRES_URI},
            id="postgresql",
            marks=pytest.mark.postgresql,
        ),
    ],
)
def test_the_integration_ready_conftest_follows_test_db(env):
    result = run_example_tests(
        "guides/testing/fixtures-and-patterns/integration_ready/test_provider.py",
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 3}


def test_the_manual_cleanup_resets_data_between_tests():
    result = run_example_tests(
        "guides/testing/fixtures-and-patterns/manual_cleanup/test_cleanup.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 2}
