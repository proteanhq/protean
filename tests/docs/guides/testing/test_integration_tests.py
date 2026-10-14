"""The examples on ``docs/guides/testing/integration-tests.md`` pass under pytest.

The domain runs its handlers asynchronously, so each test passes only when the
test-mode engine, ``process_and_wait`` or ``drain`` processes the cascade.

The order-flow feature runs under the conftest that picks its database from
``TEST_DB``, once with the default in-memory adapter and once with SQLite.
"""

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def test_the_integration_test_examples_pass():
    result = run_example_tests("guides/testing/integration-tests/001.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 5}


# A bare "sqlite" id would become a keyword, and the suite's conftest skips a
# test with that keyword unless --sqlite is given. SQLite needs no service.
@pytest.mark.parametrize(
    "test_db", ["memory", "sqlite"], ids=["memory-adapter", "sqlite-adapter"]
)
def test_the_order_flow_scenarios_pass_on_each_adapter(test_db):
    result = run_example_tests(
        "guides/testing/integration-tests/integration/test_order_flow.py",
        env={"TEST_DB": test_db},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 2}
