"""Generic schema management tests that run against providers with SCHEMA_MANAGEMENT capability.

Covers create_schema(), drop_schema(), and the
ability to create/drop database structures (tables, indices, etc.).

These tests only run against providers that declare SCHEMA_MANAGEMENT
in their capabilities (e.g., PostgreSQL, SQLite, MSSQL, Elasticsearch).
Memory provider does NOT support schema management.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasMany, Integer, String
from tests.shared import provider_adapter


class SchemaUser(BaseAggregate):
    name: String(max_length=100, required=True)
    email: String(max_length=255, required=True)


class SchemaOrder(BaseAggregate):
    customer_name: String(max_length=100, required=True)
    total: Integer(default=0)
    line_items = HasMany("SchemaLineItem")


class SchemaLineItem(BaseEntity):
    sku: String(max_length=50, required=True)
    quantity: Integer(default=1)


@pytest.mark.schema_management
class TestCreateDatabaseArtifacts:
    """Test create_schema() creates required structures."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(SchemaUser)

    def test_create_artifacts_enables_persistence(self, test_domain):
        """After create_schema, data can be persisted and retrieved."""
        provider = provider_adapter(test_domain, "default")
        provider.create_schema()

        try:
            test_domain.repository_for(SchemaUser).add(
                SchemaUser(name="Alice", email="alice@example.com")
            )

            results = test_domain.repository_for(SchemaUser)._dao.query.all()
            assert results.total == 1
            assert results.first.name == "Alice"
        finally:
            provider.drop_schema()

    def test_create_artifacts_is_idempotent(self, test_domain):
        """Calling create_schema multiple times does not error."""
        provider = provider_adapter(test_domain, "default")

        try:
            provider.create_schema()
            provider.create_schema()  # Should not raise

            test_domain.repository_for(SchemaUser).add(
                SchemaUser(name="Bob", email="bob@example.com")
            )
            assert test_domain.repository_for(SchemaUser)._dao.query.all().total == 1
        finally:
            provider.drop_schema()

    def test_create_artifacts_for_multiple_aggregates(self, test_domain):
        """create_schema handles multiple registered aggregates."""
        test_domain.register(SchemaOrder)
        test_domain.register(SchemaLineItem, part_of=SchemaOrder)
        test_domain.init(traverse=False)

        provider = provider_adapter(test_domain, "default")

        try:
            provider.create_schema()

            test_domain.repository_for(SchemaUser).add(
                SchemaUser(name="Alice", email="alice@example.com")
            )
            test_domain.repository_for(SchemaOrder).add(
                SchemaOrder(customer_name="Bob", total=100)
            )

            assert test_domain.repository_for(SchemaUser)._dao.query.all().total == 1
            assert test_domain.repository_for(SchemaOrder)._dao.query.all().total == 1
        finally:
            provider.drop_schema()


@pytest.mark.schema_management
class TestDropDatabaseArtifacts:
    """Test drop_schema() removes structures."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(SchemaUser)

    def test_drop_artifacts_is_idempotent(self, test_domain):
        """Calling drop_schema multiple times does not error."""
        provider = provider_adapter(test_domain, "default")
        provider.create_schema()
        provider.drop_schema()
        provider.drop_schema()  # Should not raise

    def test_has_table_true_after_create(self, test_domain):
        """After create_schema, has_table() returns True."""
        provider = provider_adapter(test_domain, "default")

        try:
            provider.create_schema()
            dao = test_domain.repository_for(SchemaUser)._dao
            assert dao.has_table() is True
        finally:
            provider.drop_schema()

    def test_has_table_false_after_drop(self, test_domain):
        """After drop_schema, has_table() returns False."""
        provider = provider_adapter(test_domain, "default")
        provider.create_schema()
        provider.drop_schema()

        dao = test_domain.repository_for(SchemaUser)._dao
        assert dao.has_table() is False


@pytest.mark.schema_management
class TestDomainSchemaHelpers:
    """Test domain-level schema management helpers."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(SchemaUser)

    def test_setup_database_creates_artifacts(self, test_domain):
        """domain.setup_database() delegates to create_schema()."""
        test_domain.setup_database()

        try:
            test_domain.repository_for(SchemaUser).add(
                SchemaUser(name="Alice", email="alice@example.com")
            )
            assert test_domain.repository_for(SchemaUser)._dao.query.all().total == 1
        finally:
            test_domain.drop_database()

    def test_drop_database_delegates_to_provider(self, test_domain):
        """domain.drop_database() delegates to drop_schema()."""
        test_domain.setup_database()
        test_domain.drop_database()

        # Verify structures were removed
        dao = test_domain.repository_for(SchemaUser)._dao
        assert dao.has_table() is False

    def test_setup_database_is_idempotent(self, test_domain):
        """Calling setup_database() multiple times does not error."""
        try:
            test_domain.setup_database()
            test_domain.setup_database()  # Should not raise

            test_domain.repository_for(SchemaUser).add(
                SchemaUser(name="Alice", email="alice@example.com")
            )
            assert test_domain.repository_for(SchemaUser)._dao.query.all().total == 1
        finally:
            test_domain.drop_database()
