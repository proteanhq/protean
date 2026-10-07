"""Run the example on ``docs/reference/adapters/cache/index.md``."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_ttl_of_a_cached_key_is_reported_in_seconds():
    example = load_example("adapters/cache/index/001.py")

    assert example.present == "60s left"


def test_missing_key_has_no_ttl():
    example = load_example("adapters/cache/index/001.py")

    assert example.missing == "missing"
