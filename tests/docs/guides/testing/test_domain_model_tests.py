"""The examples on ``docs/guides/testing/domain-model-tests.md`` pass under pytest."""

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def test_the_domain_model_tests_pass():
    result = run_example_tests("guides/testing/domain-model-tests/001.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 11}
