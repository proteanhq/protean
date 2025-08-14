"""Module to test PostgreSQL Provider specific functionality"""

import pytest
from sqlalchemy.engine.result import Result
from sqlalchemy.orm.session import Session

from protean import Domain
from protean.adapters.repository.sqlalchemy import PostgresqlProvider
from protean.exceptions import ConfigurationError

from .elements import Alien, Person


@pytest.mark.postgresql
class TestPostgresqlProvider:
    """Test PostgreSQL-specific provider functionality"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(Alien)
        test_domain.init(traverse=False)

    def test_provider_type_is_postgresql(self, test_domain):
        """Test that provider is of correct PostgreSQL type"""
        provider = test_domain.providers["default"]
        assert isinstance(provider, PostgresqlProvider)

    def test_provider_get_connection_returns_sqlalchemy_session(self, test_domain):
        """Test that get_connection returns SQLAlchemy session"""
        conn = test_domain.providers["default"].get_connection()
        assert conn is not None
        assert isinstance(conn, Session)

    @pytest.mark.no_test_domain
    def test_exception_on_invalid_postgresql_provider(self):
        """Test exception on invalid PostgreSQL provider"""
        domain = Domain()
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": "postgresql://postgres:postgres@localhost:5444/foobar",
        }
        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        assert "Could not connect to database at" in str(exc.value)

    def test_postgresql_raw_queries_with_sql(self, test_domain):
        """Test PostgreSQL-specific raw SQL queries"""
        test_domain.repository_for(Person)._dao.create(
            first_name="Murdock", age=7, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Jean", age=3, last_name="John"
        )
        test_domain.repository_for(Person)._dao.create(
            first_name="Bart", age=6, last_name="Carrie"
        )

        test_domain.repository_for(Alien)._dao.create(
            first_name="Sully", age=28, last_name="Monster"
        )
        test_domain.repository_for(Alien)._dao.create(
            first_name="Mike", age=26, last_name="Monster"
        )
        test_domain.repository_for(Alien)._dao.create(
            first_name="Boo", age=2, last_name="Human"
        )

        provider = test_domain.providers["default"]

        # Filter by column value - PostgreSQL specific SQL
        results = provider.raw("SELECT count(*) FROM person where last_name = 'John'")
        assert isinstance(results, Result)
        assert next(results)[0] == 2

        results = provider.raw(
            "SELECT count(*) FROM person where last_name = 'John' and age = 3"
        )
        assert next(results)[0] == 1

        # This query brings results from multiple repositories
        results = provider.raw("SELECT count(*) FROM person where age in (6,3)")
        assert next(results)[0] == 2

        results = provider.raw(
            "SELECT first_name FROM person where last_name = 'John' and age in (6,7)"
        )
        assert next(results)[0] == "Murdock"
