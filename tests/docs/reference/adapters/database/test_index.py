"""Run the example on ``docs/reference/adapters/database/index.md``."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_raw_query_returns_only_matching_rows():
    example = load_example("adapters/database/index/001.py")

    # Tim is 17, so the "age__gt": 21 filter leaves only Ada
    assert [(row["name"], row["age"]) for row in example.results] == [("Ada", 36)]
