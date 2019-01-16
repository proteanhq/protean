"""Tests for Repository Functionality"""

import pytest
from tests.support.dog import Dog

from protean.core.exceptions import ObjectNotFoundError
from protean.core.exceptions import ValidationError
from protean.core.repository import repo_factory
from protean.impl.repository.dict_repo import _databases


class TestRepository:
    """This class holds tests for Repository class"""

    def test_init(self):
        """Test successful access to the Dog repository"""

        Dog.filter()
        current_db = dict(repo_factory.Dog.conn)
        assert current_db['data'] == {'dogs': {}}

    def test_create_error(self):
        """ Add an entity to the repository missing a required attribute"""
        with pytest.raises(ValidationError):
            Dog.create(owner='John')

    def test_create(self):
        """ Add an entity to the repository"""
        dog = Dog.create(id=11344234, name='Johnny', owner='John')
        assert dog is not None
        assert dog.id == 11344234
        assert dog.name == 'Johnny'
        assert dog.age == 5
        assert dog.owner == 'John'

        dog = Dog.get(11344234)
        assert dog is not None

    def test_update(self):
        """ Update an existing entity in the repository"""
        dog = Dog.create(id=2, name='Johnny', owner='Carey', age=2)

        dog.update(data=dict(age=10))
        u_dog = Dog.get(2)
        assert u_dog is not None
        assert u_dog.age == 10

    def test_that_update_runs_validations(self):
        """Try updating with invalid values"""
        dog = Dog.create(id=1, name='Johnny', owner='Carey', age=2)

        with pytest.raises(ValidationError):
            dog.update(data=dict(age='x'))

    def test_unique(self):
        """ Test the unique constraints for the entity """
        Dog.create(id=2, name='Johnny', owner='Carey')

        with pytest.raises(ValidationError) as err:
            Dog.create(
                id=2, name='Johnny', owner='Carey')
        assert err.value.normalized_messages == {
            'name': ['`dogs` with this `name` already exists.']}

    def test_filter(self):
        """ Query the repository using filters """
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = Dog.filter(owner='John')
        assert dogs is not None
        assert dogs.total == 2
        assert len(dogs.items) == 2

        # Order the results by age
        dogs = Dog.filter(owner='John', order_by=['-age'])
        assert dogs is not None
        assert dogs.first.age == 7
        assert dogs.first.name == 'Murdock'

    def test_pagination(self):
        """ Test the pagination of the filter results"""
        for counter in range(1, 5):
            Dog.create(id=counter, name=counter, owner='Owner Name')

        dogs = Dog.filter(per_page=2, order_by=['id'])
        assert dogs is not None
        assert dogs.total == 4
        assert len(dogs.items) == 2
        assert dogs.first.id == 1
        assert dogs.has_next
        assert not dogs.has_prev

        dogs = Dog.filter(page=2, per_page=2, order_by=['id'])
        assert len(dogs.items) == 2
        assert dogs.first.id == 3
        assert not dogs.has_next
        assert dogs.has_prev

    def test_delete(self):
        """ Delete an object in the reposoitory by ID"""
        dog = Dog.create(id=3, name='Johnny', owner='Carey')
        del_count = dog.delete()
        assert del_count == 1

        del_count = dog.delete()
        assert del_count == 0

        with pytest.raises(ObjectNotFoundError):
            Dog.get(3)

    def test_close_connections(self):
        """ Test closing all connections to the repository"""
        assert 'default' in _databases
        repo_factory.close_connections()
