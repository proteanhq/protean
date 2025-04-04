from protean.adapters.repository.sqlalchemy import PostgresqlProvider, SqliteProvider


class TestAdditionalEngineArgs:
    """Test suite for SAProvider._additional_engine_args method"""

    def test_basic_extraction_of_arguments(self, test_domain):
        provider = SqliteProvider(
            name="test_provider",
            domain=test_domain,
            conn_info={
                "provider": "sqlite",
                "database_uri": "sqlite:///:memory:",
                "echo": True,
                "pool_size": 10,
                "pool_recycle": 1800,
            },
        )

        result = provider._additional_engine_args()

        assert "echo" in result
        assert result["echo"] is True
        assert "pool_size" in result
        assert result["pool_size"] == 10
        assert "pool_recycle" in result
        assert result["pool_recycle"] == 1800

    def test_excluded_keys_are_not_included(self, test_domain):
        provider = PostgresqlProvider(
            name="test_provider",
            domain=test_domain,
            conn_info={
                "provider": "postgresql",
                "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
                "SCHEMA": "test_schema",
                "echo": True,
            },
        )

        result = provider._additional_engine_args()

        assert "provider" not in result
        assert "database_uri" not in result
        assert "SCHEMA" not in result
        assert "echo" in result

    def test_database_specific_args_are_included(self, test_domain):
        provider = PostgresqlProvider(
            name="test_provider",
            domain=test_domain,
            conn_info={
                "provider": "postgresql",
                "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
                "echo": True,
            },
        )

        result = provider._additional_engine_args()

        assert "echo" in result
        assert result["echo"] is True
        assert "isolation_level" in result
        assert result["isolation_level"] == "AUTOCOMMIT"

    def test_database_specific_args_override_conn_info_args(self, test_domain):
        """Test that args in conn_info override default database-specific args with the same key"""
        provider = PostgresqlProvider(
            name="test_provider",
            domain=test_domain,
            conn_info={
                "provider": "postgresql",
                "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
                "isolation_level": "SERIALIZABLE",
                "echo": True,
            },
        )

        result = provider._additional_engine_args()

        assert "isolation_level" in result
        assert result["isolation_level"] == "SERIALIZABLE"  # Overridden value

    def test_minimal_conn_info(self, test_domain):
        provider = SqliteProvider(
            name="test_provider",
            domain=test_domain,
            conn_info={
                "provider": "sqlalchemy",
                "database_uri": "sqlite:///:memory:",
            },
        )

        result = provider._additional_engine_args()

        assert result == {}

    def test_integration_with_postgresql_provider(self, test_domain):
        provider = PostgresqlProvider(
            name="test_provider",
            domain=test_domain,
            conn_info={
                "provider": "sqlalchemy",
                "database_uri": "postgresql://user:pass@localhost/testdb",
                "echo": True,
            },
        )

        result = provider._additional_engine_args()

        assert "echo" in result
        assert result["echo"] is True
        assert "isolation_level" in result
        assert result["isolation_level"] == "AUTOCOMMIT"

    def test_integration_with_sqlite_provider(self, test_domain):
        provider = SqliteProvider(
            name="test_provider",
            domain=test_domain,
            conn_info={
                "provider": "sqlalchemy",
                "database_uri": "sqlite:///:memory:",
                "echo": True,
            },
        )

        result = provider._additional_engine_args()

        assert "echo" in result
        assert result["echo"] is True
        assert "isolation_level" not in result
