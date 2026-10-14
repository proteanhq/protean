"""The examples on ``docs/guides/testing/event-sourcing-tests.md`` pass under pytest."""

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def test_the_event_sourcing_tests_pass():
    result = run_example_tests("guides/testing/event-sourcing-tests/001.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 16}
