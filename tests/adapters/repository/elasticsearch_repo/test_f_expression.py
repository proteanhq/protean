"""Elasticsearch loud-fail coverage for ``F`` column references.

Column-to-column comparison on Elasticsearch would need a Painless script
query, which is not implemented. The adapter must fail loudly with an
actionable message rather than diverge silently from the other adapters.
"""

import pytest

from protean import F
from protean.adapters.repository import elasticsearch as repo


@pytest.mark.elasticsearch
class TestElasticsearchFExpression:
    def test_comparison_lookup_with_f_raises(self, test_domain):
        lookup = repo.LessThan("retry_count", F("max_retries"))

        with pytest.raises(NotImplementedError) as exc:
            lookup.as_expression()

        message = str(exc.value)
        assert "F('max_retries')" in message
        assert "Elasticsearch" in message
        assert "script" in message

    def test_exact_lookup_with_f_raises(self, test_domain):
        lookup = repo.Exact("retry_count", F("max_retries"))

        with pytest.raises(NotImplementedError):
            lookup.as_expression()

    def test_literal_target_is_unaffected(self, test_domain):
        # A non-F target still renders the standard range query.
        lookup = repo.LessThan("age", 6)

        assert lookup.as_expression().to_dict() == {"range": {"age": {"lt": 6}}}
