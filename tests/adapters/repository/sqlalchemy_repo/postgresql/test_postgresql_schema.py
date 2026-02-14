"""Module to test PostgreSQL schema handling functionality"""

import pytest
from sqlalchemy import inspect

from protean import Domain
from protean.adapters.repository.sqlalchemy import PostgresqlProvider
from protean.core.aggregate import BaseAggregate
from protean.fields import String, Integer


@pytest.mark.postgresql
class TestPostgreSQLSchemaHandling:
    """Test PostgreSQL-specific schema functionality"""

    def test_default_schema_is_public(self, test_domain):
        """Test that default schema is 'public' for PostgreSQL"""
        provider = test_domain.providers["default"]
        assert isinstance(provider, PostgresqlProvider)
        assert provider._metadata.schema == "public"

    def test_custom_schema_configuration_via_conn_info(self):
        """Test that custom schema can be configured via schema in conn_info"""
        domain = Domain("Test Custom Schema")
        domain.config["databases"]["custom_schema"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
            "schema": "test_schema",
        }
        domain.init(traverse=False)

        provider = domain.providers["custom_schema"]
        assert provider._metadata.schema == "test_schema"

    def test_schema_none_defaults_to_public(self):
        """Test that when no schema is specified, it defaults to 'public'"""
        domain = Domain("Test Default Schema")
        domain.config["databases"]["default_schema"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        }
        domain.init(traverse=False)

        provider = domain.providers["default_schema"]
        assert provider._metadata.schema == "public"

    def test_existing_tables_are_in_configured_schema(self, test_domain):
        """Test that existing tables are in the configured schema"""
        provider = test_domain.providers["default"]

        # Verify existing tables are in the correct schema
        inspector = inspect(provider._engine)
        schema_name = provider._metadata.schema

        # Check that some known tables exist in the configured schema
        tables = inspector.get_table_names(schema=schema_name)
        # We know these tables should exist from the conftest setup
        assert "person" in tables
        assert "alien" in tables

    @pytest.mark.no_test_domain
    def test_table_inspection_works_with_schema(self):
        """Test that table inspection works correctly with schema"""
        # Create a fresh domain for this test
        domain = Domain("Schema Test Domain")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        }

        # Define test entity with a unique name to avoid conflicts
        class UniqueSchemaTestEntity(BaseAggregate):
            name = String(max_length=100, required=True)
            count = Integer(default=0)

        domain.register(UniqueSchemaTestEntity)
        domain.init(traverse=False)

        with domain.domain_context():
            # Get DAO and check if table exists
            dao = domain.repository_for(UniqueSchemaTestEntity)._dao

            # Initially table shouldn't exist
            assert not dao.has_table()

            # Create the table
            provider = domain.providers["default"]
            provider._create_database_artifacts()

            # Now table should exist
            assert dao.has_table()

            # Clean up
            provider._drop_database_artifacts()

    @pytest.mark.no_test_domain
    def test_custom_schema_name_in_entity_meta(self):
        """Test that custom schema_name in entity Meta is respected"""
        # Create a fresh domain for this test
        domain = Domain("Custom Schema Test Domain")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        }

        # Define test entity with custom schema name
        class UniqueCustomSchemaEntity(BaseAggregate):
            title = String(max_length=200, required=True)

        domain.register(
            UniqueCustomSchemaEntity, schema_name="unique_custom_table_name"
        )
        domain.init(traverse=False)

        with domain.domain_context():
            # Create database artifacts
            provider = domain.providers["default"]
            provider._create_database_artifacts()

            # Verify table was created with custom name
            inspector = inspect(provider._engine)
            schema_name = provider._metadata.schema
            tables = inspector.get_table_names(schema=schema_name)
            # The table should be created with the custom schema_name, not the class name
            assert "unique_custom_table_name" in tables

            # Clean up
            provider._drop_database_artifacts()

    def test_schema_isolation_between_providers(self):
        """Test that different providers can use different schemas"""
        domain = Domain("Test Schema Isolation")

        # Configure two providers with different schemas
        domain.config["databases"]["schema1"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
            "schema": "schema_one",
        }
        domain.config["databases"]["schema2"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
            "schema": "schema_two",
        }
        domain.init(traverse=False)

        provider1 = domain.providers["schema1"]
        provider2 = domain.providers["schema2"]

        assert provider1._metadata.schema == "schema_one"
        assert provider2._metadata.schema == "schema_two"

    def test_raw_sql_respects_schema_context(self, test_domain):
        """Test that raw SQL queries work within schema context"""
        # Use existing person table for this test
        from .elements import Person

        provider = test_domain.providers["default"]

        # Create a test record using the repository
        person = Person(first_name="John", last_name="Doe", age=30)
        test_domain.repository_for(Person).add(person)

        # Use raw SQL to query the table in the schema
        schema_name = provider._metadata.schema
        table_name = "person"

        # Query using fully qualified table name
        query = f'SELECT first_name, age FROM "{schema_name}"."{table_name}" WHERE first_name = :name'
        result = provider.raw(query, {"name": "John"})

        # Verify we get results
        rows = list(result)
        assert len(rows) >= 1
        # Find our record
        john_record = next((row for row in rows if row.first_name == "John"), None)
        assert john_record is not None
        assert john_record.age == 30

    @pytest.mark.no_test_domain
    def test_drop_schema_artifacts_cleans_up_properly(self):
        """Test that dropping schema artifacts cleans up tables properly"""
        # Create a fresh domain for this test
        domain = Domain("Drop Test Domain")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        }

        # Define test entity
        class DropTestEntity(BaseAggregate):
            name = String(max_length=100, required=True)

        domain.register(DropTestEntity)
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]

            # Create artifacts
            provider._create_database_artifacts()

            # Verify table exists
            dao = domain.repository_for(DropTestEntity)._dao
            assert dao.has_table()

            # Drop artifacts
            provider._drop_database_artifacts()

            # Verify table no longer exists
            assert not dao.has_table()

    def test_concurrent_schema_operations(self, test_domain):
        """Test that concurrent operations on schema work correctly"""
        from .elements import Person, Alien

        # Verify both tables exist (should be created by conftest)
        person_dao = test_domain.repository_for(Person)._dao
        alien_dao = test_domain.repository_for(Alien)._dao

        assert person_dao.has_table()
        assert alien_dao.has_table()

        # Test that both can be used simultaneously
        person = Person(first_name="Jane", last_name="Smith", age=25)
        alien = Alien(first_name="Zyx", last_name="Alien", age=100)

        test_domain.repository_for(Person).add(person)
        test_domain.repository_for(Alien).add(alien)

        # Verify both were saved
        retrieved_person = test_domain.repository_for(Person).get(person.id)
        retrieved_alien = test_domain.repository_for(Alien).get(alien.id)

        assert retrieved_person.first_name == "Jane"
        assert retrieved_alien.first_name == "Zyx"

    def test_schema_metadata_consistency(self, test_domain):
        """Test that schema metadata is consistent across operations"""
        provider = test_domain.providers["default"]

        # Check initial metadata state
        initial_schema = provider._metadata.schema
        assert initial_schema == "public"

        # Verify schema remains consistent after operations
        from .elements import Person

        person = Person(first_name="Meta", last_name="Test", age=35)
        test_domain.repository_for(Person).add(person)

        # Verify schema hasn't changed
        assert provider._metadata.schema == initial_schema

        # Verify tables are bound to correct schema
        for table in provider._metadata.tables.values():
            assert table.schema == initial_schema
