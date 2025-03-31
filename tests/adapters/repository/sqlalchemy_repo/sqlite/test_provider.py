"""Module to test SQLAlchemy Provider Class"""

import pytest
from sqlalchemy.engine.result import Result
from sqlalchemy.orm.session import Session

from protean import Domain
from protean.adapters.repository import Providers
from protean.adapters.repository.sqlalchemy import SqliteProvider
from protean.exceptions import ConfigurationError

from .elements import Alien, Person


@pytest.mark.sqlite
class TestProviders:
    """This class holds tests for Providers Singleton"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(Alien)
        test_domain.init(traverse=False)

    def test_initialization_of_providers_on_first_call(self, test_domain):
        """Test that ``providers`` object is available"""
        assert isinstance(test_domain.providers, Providers)
        assert test_domain.providers._providers is not None
        assert "default" in test_domain.providers

    def test_provider_detail(self, test_domain):
        """Test provider info loaded for tests"""

        provider1 = test_domain.providers["default"]
        assert isinstance(provider1, SqliteProvider)

    def test_provider_get_connection(self, test_domain):
        """Test ``get_connection`` method and check for connection details"""

        conn = test_domain.providers["default"].get_connection()
        assert conn is not None
        assert isinstance(conn, Session)
        assert conn.is_active

    def test_provider_is_alive(self, test_domain):
        """Test ``is_alive`` method"""
        assert test_domain.providers["default"].is_alive()

    @pytest.mark.no_test_domain
    def test_exception_on_invalid_provider(self):
        """Test exception on invalid provider"""
        domain = Domain(__file__)
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite:////C:/Users/username/foobar.db",
        }
        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        assert "Could not connect to database at" in str(exc.value)

    def test_provider_raw(self, test_domain):
        """Test raw queries"""
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

        # Filter by column value
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
