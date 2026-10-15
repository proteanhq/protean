"""The examples on ``docs/guides/testing/integration-tests.md`` pass under pytest.

The ``fulfillment`` domain in ``001.py`` runs its handlers asynchronously, so
each of its tests passes only when the test-mode engine, ``process_and_wait``
or ``drain`` processes the cascade.

The order-flow and persistence features run ``myapp`` with synchronous
processing, under the conftest that picks its database from ``TEST_DB``: once
with the default in-memory adapter, once with SQLite, and once with PostgreSQL
in the FULL leg. A test in the order-flow example checks that the provider in
use is the one ``TEST_DB`` names, so a fallback to memory fails the run.
"""

import pytest

from tests.docs.support import outcome_counts, run_example_tests
from tests.shared import POSTGRES_URI

pytestmark = pytest.mark.no_test_domain


def test_the_integration_test_examples_pass():
    result = run_example_tests("guides/testing/integration-tests/001.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 5}


# A bare "sqlite" id would become a keyword, and the suite's conftest skips a
# test with that keyword unless --sqlite is given. SQLite needs no service.
ADAPTERS = [
    pytest.param({"TEST_DB": "memory"}, id="memory-adapter"),
    pytest.param({"TEST_DB": "sqlite"}, id="sqlite-adapter"),
    pytest.param(
        {"TEST_DB": "postgresql", "DATABASE_URL": POSTGRES_URI},
        id="postgresql",
        marks=pytest.mark.postgresql,
    ),
]


@pytest.mark.parametrize("env", ADAPTERS)
def test_the_order_flow_scenarios_pass_on_each_adapter(env):
    result = run_example_tests(
        "guides/testing/integration-tests/integration/test_order_flow.py", env=env
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 3}


@pytest.mark.parametrize("env", ADAPTERS)
def test_the_persistence_scenarios_pass_on_each_adapter(env):
    result = run_example_tests(
        "guides/testing/integration-tests/integration/test_persistence.py", env=env
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 2}
