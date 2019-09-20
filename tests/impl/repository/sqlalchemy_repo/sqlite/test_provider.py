"""Module to test SQLAlchemy Provider Class"""
# Protean
import pytest

from protean.impl.repository.sqlalchemy_repo import SAProvider
from sqlalchemy.engine.result import ResultProxy
from sqlalchemy.orm.session import Session

# Local/Relative Imports
from .elements import Alien, Person


class TestProviders:
    """This class holds tests for Providers Singleton"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(Alien)

    def test_initialization_of_providers_on_first_call(self, test_domain):
        """Test that ``providers`` object is available"""
        assert test_domain.providers is None

        test_domain.get_provider('default')
        assert test_domain.providers is not None

    def test_provider_detail(self, test_domain):
        """Test provider info loaded for tests"""

        provider1 = test_domain.get_provider('default')
        assert isinstance(provider1, SAProvider)

    def test_provider_get_connection(self, test_domain):
        """Test ``get_connection`` method and check for connection details"""

        conn = test_domain.get_provider('default').get_connection()
        assert conn is not None
        assert isinstance(conn, Session)
        assert conn.is_active

    def test_provider_raw(self, test_domain):
        """Test raw queries"""
        test_domain.get_dao(Person).create(first_name='Murdock', age=7, last_name='John')
        test_domain.get_dao(Person).create(first_name='Jean', age=3, last_name='John')
        test_domain.get_dao(Person).create(first_name='Bart', age=6, last_name='Carrie')

        test_domain.get_dao(Alien).create(first_name='Sully', age=28, last_name='Monster')
        test_domain.get_dao(Alien).create(first_name='Mike', age=26, last_name='Monster')
        test_domain.get_dao(Alien).create(first_name='Boo', age=2, last_name='Human')

        provider = test_domain.get_provider('default')

        # Filter by column value
        results = provider.raw('SELECT count(*) FROM person where last_name = \'John\'')
        assert isinstance(results, ResultProxy)
        assert next(results)[0] == 2

        results = provider.raw('SELECT count(*) FROM person where last_name = \'John\' and age = 3')
        assert next(results)[0] == 1

        # This query brings results from multiple repositories
        results = provider.raw('SELECT count(*) FROM person where age in (6,3)')
        assert next(results)[0] == 2

        results = provider.raw('SELECT * FROM person where last_name = \'John\' and age in (6,7)')
        assert next(results)[0] == 'Murdock'
