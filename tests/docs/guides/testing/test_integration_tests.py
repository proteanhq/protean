"""The examples on ``docs/guides/testing/integration-tests.md`` pass under pytest.

The domain runs its handlers asynchronously, so each test passes only when the
test-mode engine, ``process_and_wait`` or ``drain`` processes the cascade. The
BDD steps on the page are not covered because pytest-bdd is not installed.
"""

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def test_the_integration_test_examples_pass():
    result = run_example_tests("guides/testing/integration-tests/001.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 5}
