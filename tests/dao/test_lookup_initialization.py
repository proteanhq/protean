"""Tests for standardized lookup initialization across all adapters.

Verifies that a ``LookupPort`` subclass and all adapter-specific lookups accept
`database_model_cls` as a keyword-only argument, providing a consistent
initialization interface regardless of the adapter.
"""

from typing import Any

import pytest

from protean.port.dao import LookupPort


class TestLookupPortSubclassInitialization:
    """A class that subclasses LookupPort and sets the three attributes."""

    class ConcreteLookup(LookupPort):
        """Minimal lookup that subclasses the Port directly."""

        lookup_name = "test"

        def __init__(
            self, source: Any, target: Any, *, database_model_cls: Any = None
        ) -> None:
            self.source, self.target = source, target
            self.database_model_cls = database_model_cls

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

    def test_port_declares_no_evaluation_method(self):
        """How a lookup becomes a query is private to the adapter."""
        for member in ("as_expression", "process_source", "process_target"):
            assert not hasattr(LookupPort, member)


class TestAdapterLookupBases:
    """Each adapter's lookup base class subclasses LookupPort."""

    def test_memory_lookup_subclasses_the_port(self):
        from protean.adapters.database.memory import MemoryLookup

        assert LookupPort in MemoryLookup.__mro__

    def test_no_memory_lookup_defines_as_expression(self):
        from protean.adapters.database.memory import MemoryDatabase, MemoryLookup

        memory_lookups = [
            lookup
            for lookup in MemoryDatabase.get_lookups().values()
            if MemoryLookup in lookup.__mro__
        ]
        assert memory_lookups
        for lookup in memory_lookups:
            assert not hasattr(lookup, "as_expression"), lookup.__name__

    def test_sql_default_lookup_subclasses_the_port(self):
        from protean.adapters.database.sqlalchemy import DefaultLookup

        assert LookupPort in DefaultLookup.__mro__

    def test_mssql_lookup_sets_the_three_attributes(self):
        from protean.adapters.database.sqlalchemy import MSSQLExact

        sentinel = object()
        lookup = MSSQLExact("name", "John", database_model_cls=sentinel)
        assert (lookup.source, lookup.target) == ("name", "John")
        assert lookup.database_model_cls is sentinel


class TestMemoryLookupInitialization:
    """Test Memory lookups work with standardized initialization."""

    def test_memory_lookup_without_database_model_cls(self):
        """Memory lookups work without database_model_cls."""
        from protean.adapters.database.memory import Exact

        lookup = Exact("John", "John")
        assert lookup.source == "John"
        assert lookup.target == "John"
        assert lookup.database_model_cls is None
        assert lookup.evaluate() is True

    def test_memory_lookup_with_database_model_cls(self):
        """Memory lookups accept database_model_cls (and ignore it)."""
        from protean.adapters.database.memory import Exact

        sentinel = object()
        lookup = Exact("John", "John", database_model_cls=sentinel)
        assert lookup.database_model_cls is sentinel
        # evaluate() works the same regardless of database_model_cls
        assert lookup.evaluate() is True

    def test_memory_lookup_database_model_cls_keyword_only(self):
        """Memory lookups reject database_model_cls as positional arg."""
        from protean.adapters.database.memory import Exact

        with pytest.raises(TypeError):
            Exact("name", "John", object())


class TestSQLAlchemyLookupInitialization:
    """Test SQLAlchemy lookups use standardized initialization."""

    def test_sa_lookup_with_database_model_cls_keyword(self):
        """SA lookups accept database_model_cls as keyword arg."""
        from protean.adapters.database.sqlalchemy import DefaultLookup

        sentinel = object()
        lookup = DefaultLookup("name", "John", database_model_cls=sentinel)
        assert lookup.source == "name"
        assert lookup.target == "John"
        assert lookup.database_model_cls is sentinel

    def test_sa_lookup_without_database_model_cls(self):
        """SA lookups can be created without database_model_cls."""
        from protean.adapters.database.sqlalchemy import DefaultLookup

        lookup = DefaultLookup("name", "John")
        assert lookup.database_model_cls is None

    def test_sa_lookup_database_model_cls_keyword_only(self):
        """SA lookups reject database_model_cls as positional arg."""
        from protean.adapters.database.sqlalchemy import DefaultLookup

        with pytest.raises(TypeError):
            DefaultLookup("name", "John", object())

    def test_sa_exact_lookup_inherits_keyword_init(self):
        """SA Exact lookup inherits the keyword-only init."""
        from protean.adapters.database.sqlalchemy import Exact

        sentinel = object()
        lookup = Exact("name", "John", database_model_cls=sentinel)
        assert lookup.database_model_cls is sentinel


@pytest.mark.elasticsearch
class TestElasticsearchLookupInitialization:
    """Test Elasticsearch lookups use standardized initialization."""

    def test_es_default_lookup_subclasses_the_port(self):
        from protean.adapters.database.elasticsearch import DefaultLookup

        assert LookupPort in DefaultLookup.__mro__

    def test_es_default_lookup_declares_its_own_as_expression(self):
        from protean.adapters.database.elasticsearch import DefaultLookup

        lookup = DefaultLookup("name", "John")
        assert lookup.process_source() == "name"
        with pytest.raises(NotImplementedError):
            lookup.as_expression()

    def test_es_lookup_with_database_model_cls_keyword(self):
        """ES lookups accept database_model_cls as keyword arg."""
        from protean.adapters.database.elasticsearch import Exact

        sentinel = object()
        lookup = Exact("name", "John", database_model_cls=sentinel)
        assert lookup.source == "name"
        assert lookup.target == "John"
        assert lookup.database_model_cls is sentinel

    def test_es_lookup_without_database_model_cls(self):
        """ES lookups can be created without database_model_cls."""
        from protean.adapters.database.elasticsearch import Exact

        lookup = Exact("name", "John")
        assert lookup.database_model_cls is None

    def test_es_lookup_database_model_cls_keyword_only(self):
        """ES lookups reject database_model_cls as positional arg."""
        from protean.adapters.database.elasticsearch import Exact

        with pytest.raises(TypeError):
            Exact("name", "John", object())

    def test_es_should_use_keyword_field_with_model_cls(self):
        """ES lookup uses cached _keyword_fields from database_model_cls."""
        from protean.adapters.database.elasticsearch import Exact

        class FakeModel:
            _keyword_fields = {"name", "status"}

        lookup = Exact("name", "John", database_model_cls=FakeModel)
        assert lookup.should_use_keyword_field("name") is True
        assert lookup.should_use_keyword_field("age") is False

    def test_es_should_use_keyword_field_without_model_cls(self):
        """ES lookup defaults to False when no model cls (strings are Keyword-mapped)."""
        from protean.adapters.database.elasticsearch import Exact

        lookup = Exact("name", "John")
        # Without database_model_cls, falls back to False — auto-generated models
        # map strings as Keyword, so no .keyword subfield is needed.
        assert lookup.should_use_keyword_field("name") is False

    def test_es_exact_lookup_inherits_keyword_init(self):
        """ES Exact lookup inherits the keyword-only init."""
        from protean.adapters.database.elasticsearch import Exact

        class FakeModel:
            _keyword_fields = {"name"}

        lookup = Exact("name", "John", database_model_cls=FakeModel)
        assert lookup.database_model_cls is FakeModel

    def test_es_range_lookup_with_database_model_cls(self):
        """ES range lookups also accept database_model_cls."""
        from protean.adapters.database.elasticsearch import GreaterThan

        lookup = GreaterThan("age", 25, database_model_cls=None)
        assert lookup.database_model_cls is None
        assert lookup.as_expression().to_dict() == {"range": {"age": {"gt": 25}}}
