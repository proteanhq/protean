from protean.adapters.database.sqlalchemy import MssqlDatabase


class TestMssqlProvider:
    """Test MSSQL Provider specific functionality"""

    def test_mssql_provider_database_setting(self):
        """Test that MSSQL provider has correct database setting"""
        assert MssqlDatabase.database_type == "mssql"

    def test_provider_type_is_mssql(self, test_domain):
        """Test that provider is of correct MSSQL type"""
        provider = test_domain.databases["default"]
        assert isinstance(provider, MssqlDatabase)
