"""The examples on ``docs/guides/testing/query-shape-tests.md`` pass under pytest.

The examples run against a SQLite file in a temporary directory, so the
assertions observe a real SQLAlchemy engine instead of the in-memory no-op.
"""

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def test_the_query_shape_tests_pass():
    result = run_example_tests("guides/testing/query-shape-tests/001.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 5}
