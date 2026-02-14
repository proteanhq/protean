"""Comprehensive tests for field type detection and caching optimization in Elasticsearch adapter"""

import pytest
from datetime import datetime

from protean.core.aggregate import BaseAggregate
from protean.fields import String, Integer, Float, Boolean, DateTime, Date


class DummyEntity(BaseAggregate):
    """Test entity with various field types for comprehensive testing"""

    # String fields - should use .keyword
    name: String(max_length=100, required=True)
    description: String(max_length=500)

    # Numeric fields - should NOT use .keyword
    age: Integer()
    score: Float()
    count: Integer(default=0)

    # Boolean field - should NOT use .keyword
    is_active: Boolean(default=True)

    # Date/time fields - should NOT use .keyword
    created_at: DateTime(default=datetime.now)
    birth_date: Date()

    # Auto field (identifier) - should NOT use .keyword (already keyword-mapped)
    # id field is automatically added by BaseAggregate


class MinimalEntity(BaseAggregate):
    """Minimal entity with just string fields"""

    title: String(max_length=100, required=True)
    content: String(max_length=1000)


class NumericEntity(BaseAggregate):
    """Entity with only numeric fields"""

    value: Integer()
    ratio: Float()
    enabled: Boolean()
    timestamp: DateTime()


@pytest.mark.elasticsearch
class TestFieldTypeDetectionIntegration:
    """Integration tests for field type detection and caching"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(DummyEntity)
        test_domain.register(MinimalEntity)
        test_domain.register(NumericEntity)
        test_domain.init(traverse=False)

    def test_comprehensive_field_type_detection(self, test_domain):
        """Test field type detection across all field types"""
        provider = test_domain.providers["default"]

        # Test comprehensive entity
        test_keyword_fields = provider._compute_keyword_fields(DummyEntity)

        # String fields should be included
        assert "name" in test_keyword_fields
        assert "description" in test_keyword_fields

        # Numeric fields should be excluded
        assert "age" not in test_keyword_fields
        assert "score" not in test_keyword_fields
        assert "count" not in test_keyword_fields

        # Boolean field should be excluded
        assert "is_active" not in test_keyword_fields

        # Date/time fields should be excluded
        assert "created_at" not in test_keyword_fields
        assert "birth_date" not in test_keyword_fields

        # Identifier field should be excluded
        assert "id" not in test_keyword_fields

    def test_minimal_entity_all_string_fields(self, test_domain):
        """Test entity with only string fields"""
        provider = test_domain.providers["default"]
        keyword_fields = provider._compute_keyword_fields(MinimalEntity)

        # All declared fields should be string fields
        assert "title" in keyword_fields
        assert "content" in keyword_fields
        assert "id" not in keyword_fields  # ID is special case

    def test_numeric_entity_no_keyword_fields(self, test_domain):
        """Test entity with only numeric/date fields"""
        provider = test_domain.providers["default"]
        keyword_fields = provider._compute_keyword_fields(NumericEntity)

        # No fields should need .keyword (all are numeric/date/boolean)
        assert "value" not in keyword_fields
        assert "ratio" not in keyword_fields
        assert "enabled" not in keyword_fields
        assert "timestamp" not in keyword_fields
        assert "id" not in keyword_fields

    def test_end_to_end_filtering_with_cached_field_types(self, test_domain):
        """Test end-to-end filtering functionality with cached field type information"""
        dao = test_domain.repository_for(DummyEntity)._dao

        # Verify the database model has cached field information
        assert hasattr(dao.database_model_cls, "_keyword_fields")

        # Create test data
        dao.create(
            name="Test Entity",
            description="A test description",
            age=25,
            score=95.5,
            is_active=True,
            count=10,
        )

        # Test string field filtering (should use .keyword)
        string_results = dao.query.filter(name="Test Entity")
        assert string_results.total == 1

        # Test description field filtering (should use .keyword)
        desc_results = dao.query.filter(description="A test description")
        assert desc_results.total == 1

        # Test integer field filtering (should NOT use .keyword)
        age_results = dao.query.filter(age=25)
        assert age_results.total == 1

        # Test float field filtering (should NOT use .keyword)
        score_results = dao.query.filter(score=95.5)
        assert score_results.total == 1

        # Test boolean field filtering (should NOT use .keyword)
        active_results = dao.query.filter(is_active=True)
        assert active_results.total == 1

        # Test multiple field combinations
        combined_results = dao.query.filter(name="Test Entity", age=25, is_active=True)
        assert combined_results.total == 1

    def test_field_type_detection_with_in_lookup(self, test_domain):
        """Test field type detection with In lookup across different field types"""
        dao = test_domain.repository_for(DummyEntity)._dao

        # Create test data
        dao.create(name="John", age=25, score=95.5, is_active=True)
        dao.create(name="Jane", age=30, score=88.0, is_active=False)
        dao.create(name="Bob", age=35, score=92.0, is_active=True)

        # Test string field In lookup (should use .keyword)
        name_results = dao.query.filter(name__in=["John", "Jane"])
        assert name_results.total == 2

        # Test integer field In lookup (should NOT use .keyword)
        age_results = dao.query.filter(age__in=[25, 30])
        assert age_results.total == 2

        # Test float field In lookup (should NOT use .keyword)
        score_results = dao.query.filter(score__in=[95.5, 88.0])
        assert score_results.total == 2

        # Test boolean field In lookup (should NOT use .keyword)
        active_results = dao.query.filter(is_active__in=[True])
        assert active_results.total == 2

    def test_field_type_detection_with_wildcard_lookups(self, test_domain):
        """Test field type detection with wildcard lookups"""
        dao = test_domain.repository_for(DummyEntity)._dao

        # Create test data
        dao.create(name="Johnson", description="Detailed description", age=25)
        dao.create(name="Jackson", description="Short desc", age=30)

        # Test contains lookup on string field (should use .keyword)
        contains_results = dao.query.filter(name__contains="son")
        assert contains_results.total == 2

        # Test startswith lookup on string field (should use .keyword)
        starts_results = dao.query.filter(name__startswith="Jo")
        assert starts_results.total == 1

        # Test endswith lookup on string field (should use .keyword)
        ends_results = dao.query.filter(name__endswith="son")
        assert ends_results.total == 2

        # Test contains on description field
        desc_contains = dao.query.filter(description__contains="desc")
        assert desc_contains.total == 2

    def test_case_sensitive_vs_insensitive_filtering(self, test_domain):
        """Test that case-sensitive (exact) vs case-insensitive (iexact) work correctly"""
        dao = test_domain.repository_for(DummyEntity)._dao

        # Create test data with mixed case
        dao.create(name="John", description="Test Description")
        dao.create(name="jane", description="test description")

        # Test exact match (case-sensitive, uses .keyword)
        exact_results = dao.query.filter(name__exact="John")
        assert exact_results.total == 1

        exact_lower = dao.query.filter(name__exact="john")
        assert exact_lower.total == 0  # Should not match due to case sensitivity

        # Test case-insensitive match (uses analyzed field)
        iexact_results = dao.query.filter(name__iexact="JOHN")
        assert iexact_results.total == 1

        iexact_lower = dao.query.filter(name__iexact="john")
        assert iexact_lower.total == 1

    def test_id_field_special_handling(self, test_domain):
        """Test that ID field is handled correctly (no .keyword suffix)"""
        dao = test_domain.repository_for(DummyEntity)._dao

        # Create test entity
        entity = dao.create(name="Test", age=25)
        entity_id = entity.id

        # Test ID field filtering (should NOT use .keyword)
        id_results = dao.query.filter(id=entity_id)
        assert id_results.total == 1

        # Test get by ID (uses exact lookup internally)
        retrieved = dao.get(entity_id)
        assert retrieved.id == entity_id
        assert retrieved.name == "Test"


@pytest.mark.elasticsearch
class TestFieldTypeDetectionEdgeCases:
    """Test edge cases and error conditions for field type detection"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(DummyEntity)
        test_domain.init(traverse=False)

    def test_unknown_field_behavior(self, test_domain):
        """Test behavior when filtering on unknown fields"""
        dao = test_domain.repository_for(DummyEntity)._dao

        # Create lookup for non-existent field
        from protean.adapters.repository.elasticsearch import Exact

        lookup = Exact("unknown_field", "value")
        lookup.database_model_cls = dao.database_model_cls

        # Unknown fields are treated as non-string fields (no .keyword)
        # This is the current behavior based on the cached field type logic
        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"term": {"unknown_field": "value"}}

    def test_lookup_without_database_model_class(self, test_domain):
        """Test lookup behavior when database_model_cls is not set"""
        from protean.adapters.repository.elasticsearch import Exact

        # Create lookup without database_model_cls
        lookup = Exact("name", "value")

        # Should fall back to using .keyword for safety
        query_dict = lookup.as_expression().to_dict()
        assert query_dict == {"term": {"name.keyword": "value"}}

    def test_empty_keyword_fields_set(self, test_domain):
        """Test behavior when entity has no string fields"""
        provider = test_domain.providers["default"]
        keyword_fields = provider._compute_keyword_fields(NumericEntity)

        # Should return empty set for entity with no string fields
        assert isinstance(keyword_fields, set)
        assert len(keyword_fields) == 0

    def test_field_type_consistency_across_operations(self, test_domain):
        """Test that field type detection is consistent across different lookup types"""
        dao = test_domain.repository_for(DummyEntity)._dao
        keyword_fields = dao.database_model_cls._keyword_fields

        # All string field lookups should behave consistently
        string_field = "name"
        numeric_field = "age"

        assert string_field in keyword_fields
        assert numeric_field not in keyword_fields

        # Test different lookup types for string field
        from protean.adapters.repository.elasticsearch import (
            Exact,
            In,
            Contains,
            Startswith,
            Endswith,
        )

        string_lookups = [
            (Exact, "John"),
            (In, ["John", "Jane"]),
            (Contains, "Jo"),
            (Startswith, "J"),
            (Endswith, "n"),
        ]

        for lookup_class, value in string_lookups:
            lookup = lookup_class(string_field, value)
            lookup.database_model_cls = dao.database_model_cls
            query = lookup.as_expression().to_dict()

            # All should use .keyword subfield for string field
            field_used = list(query.values())[0]  # Get the inner query object
            if isinstance(field_used, dict):
                field_name = list(field_used.keys())[0]
                assert field_name.endswith(".keyword"), (
                    f"{lookup_class.__name__} should use .keyword for string field"
                )

        # Test numeric field lookups
        numeric_lookups = [(Exact, 25), (In, [25, 30])]

        for lookup_class, value in numeric_lookups:
            lookup = lookup_class(numeric_field, value)
            lookup.database_model_cls = dao.database_model_cls
            query = lookup.as_expression().to_dict()

            # Should NOT use .keyword subfield for numeric field
            field_used = list(query.values())[0]
            if isinstance(field_used, dict):
                field_name = list(field_used.keys())[0]
                assert not field_name.endswith(".keyword"), (
                    f"{lookup_class.__name__} should NOT use .keyword for numeric field"
                )
