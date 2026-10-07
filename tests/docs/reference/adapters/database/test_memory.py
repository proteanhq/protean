"""Run the example on ``docs/reference/adapters/database/memory.md``."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_raw_query_applies_every_criterion():
    example = load_example("adapters/database/memory/001.py")

    # Tim is too young and Lin is inactive
    assert [row["name"] for row in example.results] == ["Ada"]
    assert example.results[0]["age"] == 36
    assert example.results[0]["status"] == "active"
