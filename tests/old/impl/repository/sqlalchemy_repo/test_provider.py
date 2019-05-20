"""Module to test Provider Class"""
# Standard Library Imports
from datetime import datetime

# Protean
from protean.conf import active_config
from protean.impl.repository.sqlalchemy_repo import SAProvider
from sqlalchemy.engine import ResultProxy
from tests.old.support.sqlalchemy.dog import SqlDog as Dog
from tests.old.support.sqlalchemy.dog import SqlRelatedDog as RelatedDog
from tests.old.support.sqlalchemy.human import SqlRelatedHuman as RelatedHuman


class TestSAProvider:
    """Class to test Connection Handler class"""

    @classmethod
    def setup_class(cls):
        """Setup actions for this test case"""
        cls.repo_conf = active_config.DATABASES['sql_db']

    def test_init(self):
        """Test Initialization of Sqlalchemy DB"""
        provider = SAProvider(self.repo_conf)
        assert provider is not None

    def test_connection(self):
        """Test the connection to the repository"""
        provider = SAProvider(self.repo_conf)
        conn = provider.get_connection()
        assert conn is not None

        # Execute a simple query to test the connection
        resp = conn.execute(
            'SELECT * FROM sqlite_master WHERE type="table"')
        assert len(list(resp)) > 1

    def test_raw(self, test_domain):
        """Test raw queries on Provider"""
        test_domain.get_repository(Dog).create(name='Cash', owner='John', age=10)
        test_domain.get_repository(Dog).create(name='Boxy', owner='Carry', age=4)
        test_domain.get_repository(Dog).create(name='Gooey', owner='John', age=2)

        john = test_domain.get_repository(RelatedHuman).create(
            name='John Doe', age=26, date_of_birth=datetime(1993, 1, 1).date())
        test_domain.get_repository(RelatedDog).create(name='Rubble', age=4, owner=john)

        provider = SAProvider(self.repo_conf)
        result = provider.raw('SELECT * FROM sql_dog')
        assert result is not None
        assert isinstance(result, ResultProxy)
        assert len(list(result)) == 3

        result = provider.raw('SELECT * FROM sql_dog WHERE owner="John"')
        assert len(list(result)) == 2

        # With a Join query, which is the whole point of this raw method
        result = provider.raw('SELECT dog.name, dog.age, human.name, human.age '
                              'FROM sql_related_dog dog INNER JOIN sql_related_human human '
                              'ON dog.owner_id = human.id')
        assert len(list(result)) == 1

        result = provider.raw('SELECT dog.name, dog.age, human.name, human.age '
                              'FROM sql_related_dog dog INNER JOIN sql_related_human human '
                              'ON dog.owner_id = human.id '
                              'WHERE dog.age = :dog_age',
                              {'dog_age': 4}
                              )
        assert len(list(result)) == 1
