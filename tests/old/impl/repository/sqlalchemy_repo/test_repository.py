"""Module to test Repository Classes and Functionality"""
# Protean
import pytest

from protean.core.exceptions import ValidationError
from tests.old.support.sqlalchemy.dog import SqlDog as Dog


class TestSqlalchemyRepository:
    """Class to test Sqlalchemy Repository"""

    @pytest.fixture(scope='function', autouse=True)
    def default_provider(self, test_domain):
        """Construct dummy Human objects for queries"""
        return test_domain.get_provider('sql_db')

    @pytest.fixture(scope='function', autouse=True)
    def conn(self, default_provider):
        """Construct dummy Human objects for queries"""
        return default_provider.get_connection()

    def test_create(self, conn, default_provider, test_domain):
        """Test creating an entity in the repository"""
        # Create the entity and validate the results
        dog = test_domain.get_repository(Dog).create(name='Johnny', owner='John')
        assert dog is not None
        assert dog.id is not None
        assert dog.name == 'Johnny'
        assert dog.age == 5

        # Check if the object is in the repo
        dog_model_cls = default_provider.get_model(Dog)
        dog_db = conn.query(dog_model_cls).get(dog.id)
        assert dog_db is not None
        assert dog_db.id == dog.id
        assert dog_db.name == 'Johnny'

        # Check for unique validation
        with pytest.raises(ValidationError) as e_info:
            test_domain.get_repository(Dog).create(name='Johnny', owner='John')
        assert e_info.value.normalized_messages == {
            'name': ['`SqlDog` with this `name` already exists.']}

    def test_update(self, conn, default_provider, test_domain):
        """Test updating an entity in the repository"""
        # Update the entity and validate the results
        dog = test_domain.get_repository(Dog).create(name='Johnny', owner='John')

        dog_reloaded = test_domain.get_repository(Dog).get(dog.id)
        test_domain.get_repository(Dog).update(dog_reloaded, age=7)
        assert dog_reloaded.age == 7

        # Check if the object is in the repo
        dog_model_cls = default_provider.get_model(Dog)
        dog_db = conn.query(dog_model_cls).get(dog.id)
        assert dog_db is not None
        assert dog_db.id == dog.id
        assert dog_db.name == 'Johnny'
        assert dog_db.age == 7

    def test_filter(self, test_domain):
        """Test reading entities from the repository"""
        test_domain.get_repository(Dog).create(name='Cash', owner='John', age=10)
        test_domain.get_repository(Dog).create(name='Boxy', owner='Carry', age=4)
        test_domain.get_repository(Dog).create(name='Gooey', owner='John', age=2)

        # Filter the entity and validate the results
        dogs = test_domain.get_repository(Dog).query.filter(owner='John').\
            limit(15).\
            order_by(['-age']).all()

        assert dogs is not None
        assert dogs.total == 2
        dog_ages = [d.age for d in dogs.items]
        assert dog_ages == [10, 2]

        # Test In and not in query
        dogs = test_domain.get_repository(Dog).query.filter(name__in=['Cash', 'Boxy'])
        assert dogs.total == 2

        dogs = test_domain.get_repository(Dog).query.filter(owner='John').exclude(name__in=['Cash', 'Gooey'])
        assert dogs.total == 0

    def test_delete(self, conn, default_provider, test_domain):
        """Test deleting an entity from the repository"""
        # Delete the entity and validate the results
        dog_predelete = test_domain.get_repository(Dog).create(name='Johnny', owner='John')

        dog = test_domain.get_repository(Dog).get(dog_predelete.id)
        dog_deleted = test_domain.get_repository(Dog).delete(dog)
        assert dog_deleted.state_.is_destroyed is True

        # Make sure that the entity is deleted
        # Check if the object is in the repo
        dog_model_cls = default_provider.get_model(Dog)
        dog_db = conn.query(dog_model_cls).filter_by(id=1).first()
        assert dog_db is None

    def test_update_all(self, test_domain):
        """Test updating an entity in the repository"""
        # Update the entity and validate the results
        test_domain.get_repository(Dog).create(name='Cash', owner='John', age=10)
        test_domain.get_repository(Dog).create(name='Boxy', owner='Carry', age=4)
        test_domain.get_repository(Dog).create(name='Gooey', owner='John', age=2)

        updated_count = test_domain.get_repository(Dog).query.filter(owner='John').update_all(age=9)
        assert updated_count == 2

        updated_dogs = test_domain.get_repository(Dog).query.filter(age=9)
        assert updated_dogs.total == 2

    def test_delete_all(self, test_domain):
        """Test updating an entity in the repository"""
        # Update the entity and validate the results
        test_domain.get_repository(Dog).create(name='Cash', owner='John', age=10)
        test_domain.get_repository(Dog).create(name='Boxy', owner='Carry', age=4)
        test_domain.get_repository(Dog).create(name='Gooey', owner='John', age=2)

        test_domain.get_repository(Dog).query.filter(owner='John').delete_all()

        remaining_dogs = test_domain.get_repository(Dog).query.all()
        assert remaining_dogs.total == 1

    def test_raw(self, test_domain):
        """Test raw queries on a Model in the repository"""
        # Update the entity and validate the results
        test_domain.get_repository(Dog).create(name='Cash', owner='John', age=10)
        test_domain.get_repository(Dog).create(name='Boxy', owner='Carry', age=4)
        test_domain.get_repository(Dog).create(name='Gooey', owner='John', age=2)

        dogs1 = test_domain.get_repository(Dog).query.raw('SELECT * FROM sql_dog')

        assert dogs1 is not None
        assert dogs1.total == 3

        dogs2 = test_domain.get_repository(Dog).query.raw('SELECT * FROM sql_dog WHERE owner="John"')
        assert dogs2.total == 2
        dog_ages = [d.age for d in dogs2.items]
        assert dog_ages == [10, 2]
