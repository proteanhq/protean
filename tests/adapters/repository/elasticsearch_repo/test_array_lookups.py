"""Elasticsearch coverage for the ``any`` and ``overlap`` array lookups.

Elasticsearch fields are natively multivalued, so both lookups render as a
``terms`` query and match documents whose array field shares any element with
the given values.
"""

import pytest

from protean.adapters.repository import elasticsearch as repo
from protean.core.aggregate import BaseAggregate
from protean.fields import List, String


class Tagged(BaseAggregate):
    name = String(max_length=50)
    tags = List(content_type=String)


@pytest.mark.elasticsearch
class TestArrayLookupExpressions:
    """Unit-level: the lookups build the expected ``terms`` query."""

    def test_any_builds_terms_query(self, test_domain):
        lookup = repo.Any("tags", ["red", "blue"])
        assert lookup.as_expression().to_dict() == {"terms": {"tags": ["red", "blue"]}}

    def test_overlap_builds_terms_query(self, test_domain):
        lookup = repo.Overlap("tags", ["red"])
        assert lookup.as_expression().to_dict() == {"terms": {"tags": ["red"]}}

    def test_any_normalises_scalar_target_to_list(self, test_domain):
        lookup = repo.Any("tags", "red")
        assert lookup.as_expression().to_dict() == {"terms": {"tags": ["red"]}}


@pytest.mark.elasticsearch
class TestArrayLookupQueries:
    """End-to-end against a live Elasticsearch index."""

    @pytest.fixture
    def repo_with_data(self, test_domain):
        test_domain.register(Tagged)
        test_domain.init(traverse=False)
        provider = test_domain.providers["default"]
        provider._create_database_artifacts()

        repository = test_domain.repository_for(Tagged)
        repository.add(Tagged(name="a", tags=["red", "blue"]))
        repository.add(Tagged(name="b", tags=["green"]))
        repository.add(Tagged(name="c", tags=["blue", "green"]))

        yield repository

        # Drop only this aggregate's index, leaving the shared ones in place.
        model_cls = repository._dao.database_model_cls
        model_cls._index.delete(using=provider.get_connection(), ignore=[404])

    def _names(self, items):
        return sorted(item.name for item in items)

    def test_any_matches_documents_sharing_a_value(self, repo_with_data):
        items = repo_with_data.query.filter(tags__any=["blue"]).all().items
        assert self._names(items) == ["a", "c"]

    def test_any_with_multiple_values(self, repo_with_data):
        items = repo_with_data.query.filter(tags__any=["red", "green"]).all().items
        assert self._names(items) == ["a", "b", "c"]

    def test_any_no_match(self, repo_with_data):
        items = repo_with_data.query.filter(tags__any=["purple"]).all().items
        assert items == []

    def test_overlap_matches_shared_elements(self, repo_with_data):
        items = repo_with_data.query.filter(tags__overlap=["green", "red"]).all().items
        assert self._names(items) == ["a", "b", "c"]
