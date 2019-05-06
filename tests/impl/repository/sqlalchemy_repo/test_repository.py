"""Module to test Repository Classes and Functionality"""
import pytest
from tests.support.sqlalchemy.dog import SqlDog as Dog

from protean.core.exceptions import ValidationError


class TestSqlalchemyRepository:
    """Class to test Sqlalchemy Repository"""

    @pytest.fixture(scope='function', autouse=True)
    def default_provider(self):
        """Construct dummy Human objects for queries"""
        from protean.core.provider import providers
        return providers.get_provider('sql_db')

    @pytest.fixture(scope='function', autouse=True)
    def conn(self, default_provider):
        """Construct dummy Human objects for queries"""
        return default_provider.get_connection()

    def test_create(self, conn, default_provider):
        """Test creating an entity in the repository"""
        # Create the entity and validate the results
        dog = Dog.create(name='Johnny', owner='John')
        assert dog is not None
        assert dog.id == 1
        assert dog.name == 'Johnny'
        assert dog.age == 5

        # Check if the object is in the repo
        dog_model_cls = default_provider.get_model(Dog)
        dog_db = conn.query(dog_model_cls).get(1)
        assert dog_db is not None
        assert dog_db.id == 1
        assert dog_db.name == 'Johnny'

        # Check for unique validation
        with pytest.raises(ValidationError) as e_info:
            Dog.create(name='Johnny', owner='John')
        assert e_info.value.normalized_messages == {
            'name': ['`SqlDog` with this `name` already exists.']}

    def test_update(self, conn, default_provider):
        """Test updating an entity in the repository"""
        # Update the entity and validate the results
        dog = Dog.create(name='Johnny', owner='John')

        dog = Dog.get(1)
        dog.update(age=7)
        assert dog is not None
        assert dog.age == 7

        # Check if the object is in the repo
        dog_model_cls = default_provider.get_model(Dog)
        dog_db = conn.query(dog_model_cls).get(1)
        assert dog_db is not None
        assert dog_db.id == 1
        assert dog_db.name == 'Johnny'
        assert dog.age == 7

    def test_filter(self):
        """Test reading entities from the repository"""
        Dog.create(name='Cash', owner='John', age=10)
        Dog.create(name='Boxy', owner='Carry', age=4)
        Dog.create(name='Gooey', owner='John', age=2)

        # Filter the entity and validate the results
        dogs = Dog.query.filter(owner='John').\
            limit(15).\
            order_by(['-age']).all()

        assert dogs is not None
        assert dogs.total == 2
        dog_ages = [d.age for d in dogs.items]
        assert dog_ages == [10, 2]

        # Test In and not in query
        dogs = Dog.query.filter(name__in=['Cash', 'Boxy'])
        assert dogs.total == 2

        dogs = Dog.query.filter(owner='John').exclude(name__in=['Cash', 'Gooey'])
        assert dogs.total == 0

    def test_delete(self, conn, default_provider):
        """Test deleting an entity from the repository"""
        # Delete the entity and validate the results
        Dog.create(name='Johnny', owner='John')

        dog = Dog.get(1)
        dog_deleted = dog.delete()
        assert dog_deleted.state_.is_destroyed is True

        # Make sure that the entity is deleted
        # Check if the object is in the repo
        dog_model_cls = default_provider.get_model(Dog)
        dog_db = conn.query(dog_model_cls).filter_by(id=1).first()
        assert dog_db is None

    def test_update_all(self):
        """Test updating an entity in the repository"""
        # Update the entity and validate the results
        Dog.create(name='Cash', owner='John', age=10)
        Dog.create(name='Boxy', owner='Carry', age=4)
        Dog.create(name='Gooey', owner='John', age=2)

        updated_count = Dog.query.filter(owner='John').update_all(age=9)
        assert updated_count == 2

        updated_dogs = Dog.query.filter(age=9)
        assert updated_dogs.total == 2

    def test_delete_all(self):
        """Test updating an entity in the repository"""
        # Update the entity and validate the results
        Dog.create(name='Cash', owner='John', age=10)
        Dog.create(name='Boxy', owner='Carry', age=4)
        Dog.create(name='Gooey', owner='John', age=2)

        Dog.query.filter(owner='John').delete_all()

        remaining_dogs = Dog.query.all()
        assert remaining_dogs.total == 1

    def test_raw(self):
        """Test raw queries on a Model in the repository"""
        # Update the entity and validate the results
        Dog.create(name='Cash', owner='John', age=10)
        Dog.create(name='Boxy', owner='Carry', age=4)
        Dog.create(name='Gooey', owner='John', age=2)

        dogs1 = Dog.query.raw('SELECT * FROM sql_dog')

        assert dogs1 is not None
        assert dogs1.total == 3

        dogs2 = Dog.query.raw('SELECT * FROM sql_dog WHERE owner="John"')
        assert dogs2.total == 2
        dog_ages = [d.age for d in dogs2.items]
        assert dog_ages == [10, 2]
