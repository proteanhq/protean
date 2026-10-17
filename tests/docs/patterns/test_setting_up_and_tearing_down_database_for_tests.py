"""Run the examples on ``docs/patterns/setting-up-and-tearing-down-database-for-tests.md``.

Each example folder holds one ``conftest.py`` the page shows and a test module
that uses its fixtures. Every pair of tests in those modules starts by checking
that a store is empty, so whichever test runs second fails if data leaked.
"""

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def _assert_passed(result, count):
    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": count}


def test_the_in_memory_conftest_resets_data_between_tests():
    _assert_passed(
        run_example_tests(
            "patterns/setting-up-and-tearing-down-database-for-tests/in_memory/test_orders.py"
        ),
        3,
    )


# A bare "sqlite" id would become a keyword, and the suite's conftest skips a
# test with that keyword unless --sqlite is given. SQLite needs no service.
@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="default-memory"),
        pytest.param({"TEST_DB": "sqlite"}, id="sqlite-adapter"),
    ],
)
def test_the_env_switch_conftest_follows_test_db(env):
    # The example's provider check asserts the default provider is the one
    # TEST_DB names, so the SQLite run fails if memory was used instead.
    result = run_example_tests(
        "patterns/setting-up-and-tearing-down-database-for-tests/env_switch/test_orders.py",
        env=env,
        args=["-v"],
    )

    _assert_passed(result, 3)
    assert "test_the_provider_follows_test_db PASSED" in result.stdout


# The memory event store keeps its messages in the memory provider, so the
# provider reset already empties it. The event-store pair checks the result,
# not that clean_data's own event-store line ran.
def test_the_manual_cleanup_resets_the_database_and_the_broker():
    _assert_passed(
        run_example_tests(
            "patterns/setting-up-and-tearing-down-database-for-tests/manual_cleanup/test_cleanup.py"
        ),
        6,
    )
