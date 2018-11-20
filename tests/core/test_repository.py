"""Tests for Repository Functionality"""

import pytest

from protean.core.entity import Entity
from protean.core.repository import repo_factory as rf
from protean.core.exceptions import ValidationError, ObjectNotFoundError
from protean.core import field
from protean.impl.repository.dict_repo import RepositorySchema


class Dog(Entity):
    """This is a dummy Dog Entity class"""
    id = field.Integer(identifier=True)
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.String(required=True, max_length=15)


class DogSchema(RepositorySchema):
    """ Schema for the Dog Entity"""

    class Meta:
        """ Meta class for schema options"""
        entity = Dog
        schema_name = 'dogs'


rf.register(DogSchema)


class TestRepository:
    """This class holds tests for Repository class"""

    def test_init(self):
        """Test successful access to the Dog repository"""

        rf.DogSchema.filter()
        current_db = dict(rf.DogSchema.conn)
        assert current_db['data'] == {'dogs': {}}

    def test_create(self):
        """ Add an entity to the repository"""
        with pytest.raises(ValidationError):
            rf.DogSchema.create(name='Johnny', owner='John')

        dog = rf.DogSchema.create(id=1, name='Johnny', owner='John')
        assert dog is not None
        assert dog.id == 1
        assert dog.name == 'Johnny'
        assert dog.age == 5
        assert dog.owner == 'John'

        dog = rf.DogSchema.get(1)
        assert dog is not None

    def test_update(self):
        """ Update an existing entity in the repository"""

        # Using an invalid id should fail
        with pytest.raises(ObjectNotFoundError):
            rf.DogSchema.update(identifier=2, data=dict(age=10))

        # Updates should run the validations
        with pytest.raises(ValidationError):
            rf.DogSchema.update(identifier=1, data=dict(age='x'))

        rf.DogSchema.update(identifier=1, data=dict(age=10))
        u_dog = rf.DogSchema.get(1)
        assert u_dog is not None
        assert u_dog.age == 10

    def test_unique(self):
        """ Test the unique constraints for the entity """

        with pytest.raises(ValidationError) as err:
            rf.DogSchema.create(
                id=2, name='Johnny', owner='Carey')
        assert err.value.normalized_messages == {
            'name': ['`dogs` with this `name` already exists.']}

    def test_filter(self):
        """ Query the repository using filters """
        # Add multiple entries to the DB
        rf.DogSchema.create(id=2, name='Murdock', age=7, owner='John')
        rf.DogSchema.create(id=3, name='Jean', age=3, owner='John')
        rf.DogSchema.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = rf.DogSchema.filter(owner='John')
        assert dogs is not None
        assert dogs.total == 3
        assert len(dogs.items) == 3

        # Order the results by age
        dogs = rf.DogSchema.filter(owner='John', order_by=['-age'])
        assert dogs is not None
        assert dogs.first.age == 10
        assert dogs.first.name == 'Johnny'

    def test_pagination(self):
        """ Test the pagination of the filter results"""
        dogs = rf.DogSchema.filter(per_page=2, order_by=['id'])
        assert dogs is not None
        assert dogs.total == 4
        assert len(dogs.items) == 2
        assert dogs.first.id == 1
        assert dogs.has_next
        assert not dogs.has_prev

        dogs = rf.DogSchema.filter(page=2, per_page=2, order_by=['id'])
        assert len(dogs.items) == 2
        assert dogs.first.id == 3
        assert not dogs.has_next
        assert dogs.has_prev

    def test_delete(self):
        """ Delete an object in the reposoitory by ID"""
        del_count = rf.DogSchema.delete(1)
        assert del_count == 1

        del_count = rf.DogSchema.delete(1)
        assert del_count == 0

        with pytest.raises(ObjectNotFoundError):
            rf.DogSchema.get(1)
