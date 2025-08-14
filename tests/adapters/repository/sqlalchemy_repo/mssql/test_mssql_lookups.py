import pytest

from protean.adapters.repository.sqlalchemy import MssqlProvider
from .elements import MssqlTestEntity


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(MssqlTestEntity)
    test_domain.init(traverse=False)


class TestMssqlLookups:
    """Test MSSQL-specific lookup functionality"""

    def test_mssql_string_lookups_registration(self):
        """Test that MSSQL string lookups are properly registered"""
        exact_lookup = MssqlProvider.get_lookups().get("exact")
        contains_lookup = MssqlProvider.get_lookups().get("contains")
        startswith_lookup = MssqlProvider.get_lookups().get("startswith")
        endswith_lookup = MssqlProvider.get_lookups().get("endswith")

        assert exact_lookup.__name__ == "MSSQLExact"
        assert contains_lookup.__name__ == "MSSQLContains"
        assert startswith_lookup.__name__ == "MSSQLStartswith"
        assert endswith_lookup.__name__ == "MSSQLEndswith"

    def test_mssql_exact_lookup_case_sensitivity(self, test_domain):
        """Test that MSSQL exact lookup is case-sensitive"""
        test_domain.register(MssqlTestEntity)
        test_domain.init(traverse=False)

        # Create test entities with different cases
        entity1 = MssqlTestEntity(name="Alice", description="First user")
        entity2 = MssqlTestEntity(name="alice", description="Second user")
        entity3 = MssqlTestEntity(name="ALICE", description="Third user")

        repo = test_domain.repository_for(MssqlTestEntity)
        repo.add(entity1)
        repo.add(entity2)
        repo.add(entity3)

        # Test case-sensitive exact match
        results = repo._dao.query.filter(name__exact="Alice").all().items
        assert len(results) == 1
        assert results[0].description == "First user"

        results = repo._dao.query.filter(name__exact="alice").all().items
        assert len(results) == 1
        assert results[0].description == "Second user"

        results = repo._dao.query.filter(name__exact="ALICE").all().items
        assert len(results) == 1
        assert results[0].description == "Third user"

        # Test non-existent case
        results = repo._dao.query.filter(name__exact="aLiCe").all().items
        assert len(results) == 0

    def test_mssql_exact_lookup_expression_generation(self, test_domain):
        """Test that MSSQL exact lookup generates correct SQL expression"""
        test_domain.register(MssqlTestEntity)
        test_domain.init(traverse=False)

        provider = test_domain.providers["default"]
        dao = provider.get_dao(
            MssqlTestEntity, provider.construct_database_model_class(MssqlTestEntity)
        )

        # Get the exact lookup class and create an instance
        exact_lookup_cls = provider.get_lookup("exact")

        # Test with string field - should apply collation
        string_lookup = exact_lookup_cls("name", "Alice", dao.database_model_cls)
        string_source = string_lookup.process_source()

        # For string fields, collation should be applied (returns BinaryExpression)
        assert (
            str(type(string_source))
            == "<class 'sqlalchemy.sql.elements.BinaryExpression'>"
        )

        # Test with integer field - should NOT apply collation
        int_lookup = exact_lookup_cls("age", 25, dao.database_model_cls)
        int_source = int_lookup.process_source()

        # For non-string fields, no collation should be applied (returns InstrumentedAttribute)
        assert (
            str(type(int_source))
            == "<class 'sqlalchemy.orm.attributes.InstrumentedAttribute'>"
        )

    def test_mssql_exact_lookup_mixed_field_query(self, test_domain):
        """Test that MSSQL exact lookup works correctly with mixed field types"""
        test_domain.register(MssqlTestEntity)
        test_domain.init(traverse=False)

        # Create test entities with mixed field values
        entity1 = MssqlTestEntity(name="Alice", description="First user", age=25)
        entity2 = MssqlTestEntity(name="alice", description="Second user", age=25)

        repo = test_domain.repository_for(MssqlTestEntity)
        repo.add(entity1)
        repo.add(entity2)

        # Test mixed query with string (case-sensitive) and integer (normal) fields
        results = repo._dao.query.filter(name__exact="Alice", age__exact=25).all().items
        assert len(results) == 1
        assert results[0].description == "First user"

        results = repo._dao.query.filter(name__exact="alice", age__exact=25).all().items
        assert len(results) == 1
        assert results[0].description == "Second user"

    def test_mssql_contains_lookup_case_sensitivity(self, test_domain):
        """Test that MSSQL contains lookup is case-sensitive"""
        test_domain.register(MssqlTestEntity)
        test_domain.init(traverse=False)

        # Create test entities with different cases in description
        entity1 = MssqlTestEntity(name="User1", description="Contains Alice", age=25)
        entity2 = MssqlTestEntity(name="User2", description="Contains alice", age=26)
        entity3 = MssqlTestEntity(name="User3", description="Contains ALICE", age=27)

        repo = test_domain.repository_for(MssqlTestEntity)
        repo.add(entity1)
        repo.add(entity2)
        repo.add(entity3)

        # Test case-sensitive contains
        results = repo._dao.query.filter(description__contains="Alice").all().items
        assert len(results) == 1
        assert results[0].name == "User1"

        results = repo._dao.query.filter(description__contains="alice").all().items
        assert len(results) == 1
        assert results[0].name == "User2"

        results = repo._dao.query.filter(description__contains="ALICE").all().items
        assert len(results) == 1
        assert results[0].name == "User3"

        # Test non-existent case
        results = repo._dao.query.filter(description__contains="aLiCe").all().items
        assert len(results) == 0
