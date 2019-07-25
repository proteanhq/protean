"""Module to test Repository extended functionality """
# Protean
import pytest

from protean import Domain
from tests.old.support.sqlalchemy.dog import SqlRelatedDog as RelatedDog
from tests.old.support.sqlalchemy.human import SqlRelatedHuman as RelatedHuman


class TestRelations:
    """Class to test Relation field of Sqlalchemy Repository"""

    @pytest.fixture(scope='function', autouse=True)
    def related_humans(self):
        """Construct dummy Human objects for queries"""
        return [
            Domain().get_repository(RelatedHuman).create(
                name='John Doe', age='30', weight='13.45', date_of_birth='01-01-1989'),
            Domain().get_repository(RelatedHuman).create(
                name='Greg Manning', age='44', weight='23.45', date_of_birth='30-07-1975')
        ]

    @pytest.fixture(scope='function', autouse=True)
    def default_provider(self, test_domain):
        """Construct dummy Human objects for queries"""
        return test_domain.get_provider('sql_db')

    @pytest.fixture(scope='function', autouse=True)
    def conn(self, default_provider):
        """Construct dummy Human objects for queries"""
        return default_provider.get_connection()

    def test_create_related(self, related_humans, test_domain):
        """Test Cceating an entity with a related field"""
        dog = RelatedDog(name='Jimmy', age=10, owner=related_humans[0])
        Domain().get_repository(RelatedDog).save(dog)

        assert dog is not None
        assert dog.owner.name == 'John Doe'

        # Check if the object is in the repo
        dog_db = test_domain.get_repository(RelatedDog).get(dog.id)
        assert dog_db is not None
        assert dog_db.owner_id == related_humans[0].id

    def test_update_related(self, conn, default_provider, related_humans, test_domain):
        """ Test updating the related field of an entity """
        test_domain.get_repository(RelatedDog).create(name='Jimmy', age=10, owner=related_humans[0])

        dog = test_domain.get_repository(RelatedDog).query.filter(name='Jimmy').all().first
        test_domain.get_repository(RelatedDog).update(dog, owner=related_humans[1])

        # Check if the object is in the repo
        dog_model_cls = default_provider.get_model(RelatedDog)
        dog_db = conn.query(dog_model_cls).get(dog.id)
        assert dog_db is not None
        assert dog_db.owner_id == related_humans[1].id

    def test_has_many(self, related_humans, test_domain):
        """ Test getting the has many attribute of Relation"""
        # Get the dogs related to the human
        assert related_humans[0].dogs is None

        # Create some dogs
        test_domain.get_repository(RelatedDog).create(name='Dex', age=6, owner=related_humans[0])
        test_domain.get_repository(RelatedDog).create(name='Lord', age=3, owner=related_humans[0])

        # Get the dogs related to the human
        assert related_humans[0].dogs is not None
        assert [d.name for d in related_humans[0].dogs] == ['Dex', 'Lord']
