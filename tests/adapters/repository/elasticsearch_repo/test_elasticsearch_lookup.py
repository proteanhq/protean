import pytest

from protean.adapters.repository import elasticsearch as repo


@pytest.mark.elasticsearch
class TestLookup:
    def test_exact_lookup(self, test_domain):
        lookup = repo.Exact("first_name", "John")

        assert lookup.as_expression().to_dict() == {"term": {"first_name": "John"}}

    def test_in_lookup(self, test_domain):
        lookup = repo.In("first_name", ["John"])

        assert lookup.as_expression().to_dict() == {"terms": {"first_name": ["John"]}}

    def test_gt_lookup(self, test_domain):
        lookup = repo.GreaterThan("age", 6)

        assert lookup.as_expression().to_dict() == {"range": {"age": {"gt": 6}}}

    def test_gte_lookup(self, test_domain):
        lookup = repo.GreaterThanOrEqual("age", 6)

        assert lookup.as_expression().to_dict() == {"range": {"age": {"gte": 6}}}

    def test_lt_lookup(self, test_domain):
        lookup = repo.LessThan("age", 6)

        assert lookup.as_expression().to_dict() == {"range": {"age": {"lt": 6}}}

    def test_lte_lookup(self, test_domain):
        lookup = repo.LessThanOrEqual("age", 6)

        assert lookup.as_expression().to_dict() == {"range": {"age": {"lte": 6}}}

    def test_contains_lookup(self, test_domain):
        lookup = repo.Contains("first_name", "John")

        assert lookup.as_expression().to_dict() == {
            "wildcard": {"first_name": {"value": "*John*"}}
        }

    def test_startswith_lookup(self, test_domain):
        lookup = repo.Startswith("first_name", "John")

        assert lookup.as_expression().to_dict() == {
            "wildcard": {"first_name": {"value": "John*"}}
        }

    def test_endswith_lookup(self, test_domain):
        lookup = repo.Endswith("first_name", "John")

        assert lookup.as_expression().to_dict() == {
            "wildcard": {"first_name": {"value": "*John"}}
        }
