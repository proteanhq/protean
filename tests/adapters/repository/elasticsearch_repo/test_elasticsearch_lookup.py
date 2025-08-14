import pytest

from protean.adapters.repository import elasticsearch as repo


@pytest.mark.elasticsearch
class TestLookup:
    def test_exact_lookup(self, test_domain):
        lookup = repo.Exact("first_name", "John")

        assert lookup.as_expression().to_dict() == {
            "term": {"first_name.keyword": "John"}
        }

    def test_in_lookup(self, test_domain):
        lookup = repo.In("first_name", ["John"])

        assert lookup.as_expression().to_dict() == {
            "terms": {"first_name.keyword": ["John"]}
        }

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
            "wildcard": {"first_name.keyword": {"value": "*John*"}}
        }

    def test_startswith_lookup(self, test_domain):
        lookup = repo.Startswith("first_name", "John")

        assert lookup.as_expression().to_dict() == {
            "wildcard": {"first_name.keyword": {"value": "John*"}}
        }

    def test_endswith_lookup(self, test_domain):
        lookup = repo.Endswith("first_name", "John")

        assert lookup.as_expression().to_dict() == {
            "wildcard": {"first_name.keyword": {"value": "*John"}}
        }


@pytest.mark.elasticsearch
class TestLookupFieldTypeDetection:
    """Test the optimized field type detection in lookup operations"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        from .elements import Person, Alien

        test_domain.register(Person)
        test_domain.register(Alien)
        test_domain.init(traverse=False)
        # Make entities available to test methods
        self.Person = Person
        self.Alien = Alien

    def test_exact_lookup_uses_keyword_for_string_fields(self, test_domain):
        """Test that Exact lookup uses .keyword subfield for string fields"""
        dao = test_domain.repository_for(self.Person)._dao

        # Create lookup with database model class attached (as done in _build_filters)
        lookup = repo.Exact("first_name", "John")
        lookup.database_model_cls = dao.database_model_cls

        # String field should use .keyword subfield
        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"term": {"first_name.keyword": "John"}}

    def test_exact_lookup_no_keyword_for_numeric_fields(self, test_domain):
        """Test that Exact lookup doesn't use .keyword subfield for numeric fields"""
        dao = test_domain.repository_for(self.Person)._dao

        # Create lookup with database model class attached
        lookup = repo.Exact("age", 25)
        lookup.database_model_cls = dao.database_model_cls

        # Numeric field should NOT use .keyword subfield
        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"term": {"age": 25}}

    def test_exact_lookup_no_keyword_for_id_field(self, test_domain):
        """Test that Exact lookup doesn't use .keyword subfield for id field"""
        dao = test_domain.repository_for(self.Person)._dao

        # Create lookup with database model class attached
        lookup = repo.Exact("id", "some-id")
        lookup.database_model_cls = dao.database_model_cls

        # ID field should NOT use .keyword subfield (already keyword mapped)
        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"term": {"id": "some-id"}}

    def test_in_lookup_uses_keyword_for_string_fields(self, test_domain):
        """Test that In lookup uses .keyword subfield for string fields"""
        dao = test_domain.repository_for(self.Person)._dao

        lookup = repo.In("first_name", ["John", "Jane"])
        lookup.database_model_cls = dao.database_model_cls

        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"terms": {"first_name.keyword": ["John", "Jane"]}}

    def test_in_lookup_no_keyword_for_numeric_fields(self, test_domain):
        """Test that In lookup doesn't use .keyword subfield for numeric fields"""
        dao = test_domain.repository_for(self.Person)._dao

        lookup = repo.In("age", [25, 30])
        lookup.database_model_cls = dao.database_model_cls

        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"terms": {"age": [25, 30]}}

    def test_contains_lookup_uses_keyword_for_string_fields(self, test_domain):
        """Test that Contains lookup uses .keyword subfield for string fields"""
        dao = test_domain.repository_for(self.Person)._dao

        lookup = repo.Contains("first_name", "Jo")
        lookup.database_model_cls = dao.database_model_cls

        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"wildcard": {"first_name.keyword": {"value": "*Jo*"}}}

    def test_contains_lookup_no_keyword_for_numeric_fields(self, test_domain):
        """Test that Contains lookup doesn't use .keyword for numeric fields"""
        dao = test_domain.repository_for(self.Person)._dao

        lookup = repo.Contains("age", "2")
        lookup.database_model_cls = dao.database_model_cls

        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"wildcard": {"age": {"value": "*2*"}}}

    def test_startswith_lookup_uses_keyword_for_string_fields(self, test_domain):
        """Test that Startswith lookup uses .keyword subfield for string fields"""
        dao = test_domain.repository_for(self.Person)._dao

        lookup = repo.Startswith("last_name", "Doe")
        lookup.database_model_cls = dao.database_model_cls

        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"wildcard": {"last_name.keyword": {"value": "Doe*"}}}

    def test_endswith_lookup_uses_keyword_for_string_fields(self, test_domain):
        """Test that Endswith lookup uses .keyword subfield for string fields"""
        dao = test_domain.repository_for(self.Person)._dao

        lookup = repo.Endswith("last_name", "son")
        lookup.database_model_cls = dao.database_model_cls

        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"wildcard": {"last_name.keyword": {"value": "*son"}}}

    def test_lookup_fallback_when_no_cached_info(self, test_domain):
        """Test that lookups fall back to using .keyword when no cached info available"""
        # Create lookup without database model class (missing cached info)
        lookup = repo.Exact("first_name", "John")

        # Should fall back to using .keyword for safety
        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"term": {"first_name.keyword": "John"}}

    def test_iexact_lookup_uses_analyzed_field(self, test_domain):
        """Test that IExact lookup uses the analyzed field (not .keyword)"""
        dao = test_domain.repository_for(self.Person)._dao

        lookup = repo.IExact("first_name", "John")
        lookup.database_model_cls = dao.database_model_cls

        # IExact should use analyzed field and lowercase the target
        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"term": {"first_name": "john"}}
