"""Run the example on ``docs/reference/adapters/database/index.md``."""

import pytest

from protean.adapters.repository.sqlalchemy import SAProvider
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_raw_query_returns_only_matching_rows():
    example = load_example("adapters/database/index/001.py")

    # Tim is 17, so the "age__gt": 21 filter leaves only Ada
    assert [(row["name"], row["age"]) for row in example.results] == [("Ada", 36)]


@pytest.mark.sqlite
def test_metadata_lists_the_aggregate_table():
    example = load_example("adapters/database/index/002.py")

    provider = example.domain.providers["default"]
    assert isinstance(provider, SAProvider)
    with example.domain.domain_context():
        assert [table.name for table in provider.metadata.sorted_tables] == ["customer"]
