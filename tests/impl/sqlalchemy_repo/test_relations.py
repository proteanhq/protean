"""Module to test Repository extended functionality """
import pytest

from tests.support.sqlalchemy.dog import SqlRelatedDog as RelatedDog
from tests.support.sqlalchemy.human import SqlRelatedHuman as RelatedHuman


class TestRelations:
    """Class to test Relation field of Sqlalchemy Repository"""

    @pytest.fixture(scope='function', autouse=True)
    def related_humans(self):
        """Construct dummy Human objects for queries"""
        return [
            RelatedHuman.create(name='John Doe', age='30', weight='13.45',
                                date_of_birth='01-01-1989'),
            RelatedHuman.create(name='Greg Manning', age='44', weight='23.45',
                                date_of_birth='30-07-1975')
        ]

    @pytest.fixture(scope='function', autouse=True)
    def default_provider(self):
        """Construct dummy Human objects for queries"""
        from protean.core.provider import providers
        return providers.get_provider('sql_db')

    @pytest.fixture(scope='function', autouse=True)
    def conn(self, default_provider):
        """Construct dummy Human objects for queries"""
        return default_provider.get_connection()

    def test_create_related(self, related_humans):
        """Test Cceating an entity with a related field"""
        dog = RelatedDog(name='Jimmy', age=10, owner=related_humans[0])
        dog.save()

        assert dog is not None
        assert dog.owner.name == 'John Doe'

        # Check if the object is in the repo
        dog_db = RelatedDog.get(dog.id)
        assert dog_db is not None
        assert dog_db.owner_id == related_humans[0].id

    def test_update_related(self, conn, default_provider, related_humans):
        """ Test updating the related field of an entity """
        RelatedDog.create(name='Jimmy', age=10, owner=related_humans[0])

        dog = RelatedDog.query.filter(name='Jimmy').all().first
        dog.update(owner=related_humans[1])

        # Check if the object is in the repo
        dog_model_cls = default_provider.get_model(RelatedDog)
        dog_db = conn.query(dog_model_cls).get(dog.id)
        assert dog_db is not None
        assert dog_db.owner_id == related_humans[1].id

    def test_has_many(self, related_humans):
        """ Test getting the has many attribute of Relation"""
        # Get the dogs related to the human
        assert related_humans[0].dogs is None

        # Create some dogs
        RelatedDog.create(name='Dex', age=6, owner=related_humans[0])
        RelatedDog.create(name='Lord', age=3, owner=related_humans[0])

        # Get the dogs related to the human
        assert related_humans[0].dogs is not None
        assert [d.name for d in related_humans[0].dogs] == ['Dex', 'Lord']
