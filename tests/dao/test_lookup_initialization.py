"""Tests for standardized lookup initialization across all adapters.

Phase 6I: Verifies that BaseLookup and all adapter-specific lookups accept
`database_model_cls` as a keyword-only argument, providing a consistent
initialization interface regardless of the adapter.
"""

import pytest

from protean.port.dao import BaseLookup


class TestBaseLookupInitialization:
    """Test BaseLookup accepts database_model_cls as keyword-only arg."""

    class ConcreteLookup(BaseLookup):
        """Minimal concrete implementation for testing."""

        lookup_name = "test"

        def as_expression(self):
            return f"{self.source} == {self.target}"

    def test_init_without_database_model_cls(self):
        """Lookup can be created with just source and target."""
        lookup = self.ConcreteLookup("name", "John")
        assert lookup.source == "name"
        assert lookup.target == "John"
        assert lookup.database_model_cls is None

    def test_init_with_database_model_cls_keyword(self):
        """Lookup accepts database_model_cls as keyword arg."""
        sentinel = object()
        lookup = self.ConcreteLookup("name", "John", database_model_cls=sentinel)
        assert lookup.source == "name"
        assert lookup.target == "John"
        assert lookup.database_model_cls is sentinel

    def test_database_model_cls_is_keyword_only(self):
        """database_model_cls cannot be passed as a positional arg."""
        with pytest.raises(TypeError):
            self.ConcreteLookup("name", "John", object())

    def test_process_source_default(self):
        """process_source returns source unchanged by default."""
        lookup = self.ConcreteLookup("name", "John")
        assert lookup.process_source() == "name"

    def test_process_target_default(self):
        """process_target returns target unchanged by default."""
        lookup = self.ConcreteLookup("name", "John")
        assert lookup.process_target() == "John"


class TestMemoryLookupInitialization:
    """Test Memory lookups work with standardized initialization."""

    def test_memory_lookup_without_database_model_cls(self):
        """Memory lookups work without database_model_cls."""
        from protean.adapters.repository.memory import Exact

        lookup = Exact("name", "John")
        assert lookup.source == "name"
        assert lookup.target == "John"
        assert lookup.database_model_cls is None
        assert lookup.as_expression() == '"name" == "John"'

    def test_memory_lookup_with_database_model_cls(self):
        """Memory lookups accept database_model_cls (and ignore it)."""
        from protean.adapters.repository.memory import Exact

        sentinel = object()
        lookup = Exact("name", "John", database_model_cls=sentinel)
        assert lookup.database_model_cls is sentinel
        # Expression works the same regardless of database_model_cls
        assert lookup.as_expression() == '"name" == "John"'

    def test_memory_lookup_database_model_cls_keyword_only(self):
        """Memory lookups reject database_model_cls as positional arg."""
        from protean.adapters.repository.memory import Exact

        with pytest.raises(TypeError):
            Exact("name", "John", object())


class TestSQLAlchemyLookupInitialization:
    """Test SQLAlchemy lookups use standardized initialization."""

    def test_sa_lookup_with_database_model_cls_keyword(self):
        """SA lookups accept database_model_cls as keyword arg."""
        from protean.adapters.repository.sqlalchemy import DefaultLookup

        sentinel = object()
        lookup = DefaultLookup("name", "John", database_model_cls=sentinel)
        assert lookup.source == "name"
        assert lookup.target == "John"
        assert lookup.database_model_cls is sentinel

    def test_sa_lookup_without_database_model_cls(self):
        """SA lookups can be created without database_model_cls."""
        from protean.adapters.repository.sqlalchemy import DefaultLookup

        lookup = DefaultLookup("name", "John")
        assert lookup.database_model_cls is None

    def test_sa_lookup_database_model_cls_keyword_only(self):
        """SA lookups reject database_model_cls as positional arg."""
        from protean.adapters.repository.sqlalchemy import DefaultLookup

        with pytest.raises(TypeError):
            DefaultLookup("name", "John", object())

    def test_sa_exact_lookup_inherits_keyword_init(self):
        """SA Exact lookup inherits the keyword-only init."""
        from protean.adapters.repository.sqlalchemy import Exact

        sentinel = object()
        lookup = Exact("name", "John", database_model_cls=sentinel)
        assert lookup.database_model_cls is sentinel


@pytest.mark.elasticsearch
class TestElasticsearchLookupInitialization:
    """Test Elasticsearch lookups use standardized initialization.

    ES DefaultLookup inherits BaseLookup's abstract as_expression(),
    so we test via concrete subclasses (Exact, GreaterThan, etc.).
    """

    def test_es_lookup_with_database_model_cls_keyword(self):
        """ES lookups accept database_model_cls as keyword arg."""
        from protean.adapters.repository.elasticsearch import Exact

        sentinel = object()
        lookup = Exact("name", "John", database_model_cls=sentinel)
        assert lookup.source == "name"
        assert lookup.target == "John"
        assert lookup.database_model_cls is sentinel

    def test_es_lookup_without_database_model_cls(self):
        """ES lookups can be created without database_model_cls."""
        from protean.adapters.repository.elasticsearch import Exact

        lookup = Exact("name", "John")
        assert lookup.database_model_cls is None

    def test_es_lookup_database_model_cls_keyword_only(self):
        """ES lookups reject database_model_cls as positional arg."""
        from protean.adapters.repository.elasticsearch import Exact

        with pytest.raises(TypeError):
            Exact("name", "John", object())

    def test_es_should_use_keyword_field_with_model_cls(self):
        """ES lookup uses cached _keyword_fields from database_model_cls."""
        from protean.adapters.repository.elasticsearch import Exact

        class FakeModel:
            _keyword_fields = {"name", "status"}

        lookup = Exact("name", "John", database_model_cls=FakeModel)
        assert lookup.should_use_keyword_field("name") is True
        assert lookup.should_use_keyword_field("age") is False

    def test_es_should_use_keyword_field_without_model_cls(self):
        """ES lookup defaults to True for keyword fields when no model cls."""
        from protean.adapters.repository.elasticsearch import Exact

        lookup = Exact("name", "John")
        # Without database_model_cls, falls back to True for safety
        assert lookup.should_use_keyword_field("name") is True

    def test_es_exact_lookup_inherits_keyword_init(self):
        """ES Exact lookup inherits the keyword-only init."""
        from protean.adapters.repository.elasticsearch import Exact

        class FakeModel:
            _keyword_fields = {"name"}

        lookup = Exact("name", "John", database_model_cls=FakeModel)
        assert lookup.database_model_cls is FakeModel

    def test_es_range_lookup_with_database_model_cls(self):
        """ES range lookups also accept database_model_cls."""
        from protean.adapters.repository.elasticsearch import GreaterThan

        lookup = GreaterThan("age", 25, database_model_cls=None)
        assert lookup.database_model_cls is None
        assert lookup.as_expression().to_dict() == {"range": {"age": {"gt": 25}}}
