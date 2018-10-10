"""Tests for Repository Functionality"""

import pytest

from protean.core.entity import Entity
from protean.core.exceptions import ValidationError, ObjectNotFoundError
from protean.core import field

from ..support.dict_repo import drf, DictSchema, DictRepository


class Dog(Entity):
    """This is a dummy Dog Entity class"""
    id = field.Integer(identifier=True)
    name = field.String(required=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.String(required=True, max_length=15)


class DogSchema(DictSchema):
    """ Schema for the Dog Entity"""

    class Meta:
        """ Meta class for schema options"""
        entity = Dog
        schema_name = 'dogs'


drf.register(DictRepository, DogSchema)


class TestRepository:
    """This class holds tests for Repository class"""

    def test_init(self, config):
        """Test successful access to the Dog repository"""

        drf.DogSchema.filter()
        current_db = dict(drf.DogSchema.db)
        assert current_db == {'dogs': {}}

    def test_create(self):
        """ Add an entity to the repository"""
        with pytest.raises(ValidationError):
            drf.DogSchema.create(name='Johnny', owner='John')

        dog = drf.DogSchema.create(id=1, name='Johnny', owner='John')
        assert dog is not None
        assert dog.id == 1
        assert dog.name == 'Johnny'
        assert dog.age == 5
        assert dog.owner == 'John'

        dog = drf.DogSchema.get(1)
        assert dog is not None

    def test_update(self):
        """ Update an existing entity in the repository"""

        # Using an invalid id should fail
        with pytest.raises(ObjectNotFoundError):
            drf.DogSchema.update(identifier=2, data=dict(age=10))

        # Updates should run the validations
        with pytest.raises(ValidationError):
            drf.DogSchema.update(identifier=1, data=dict(age='x'))

        drf.DogSchema.update(identifier=1, data=dict(age=10))
        u_dog = drf.DogSchema.get(1)
        assert u_dog is not None
        assert u_dog.age == 10

    def test_filter(self):
        """ Query the repository using filters """
        # Add multiple entries to the DB
        drf.DogSchema.create(id=2, name='Murdock', age=7, owner='John')
        drf.DogSchema.create(id=3, name='Jean', age=3, owner='John')
        drf.DogSchema.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = drf.DogSchema.filter(owner='John')
        assert dogs is not None
        assert dogs.total == 3
        assert len(dogs.items) == 3

        # Order the results by age
        dogs = drf.DogSchema.filter(owner='John', order_by=['-age'])
        assert dogs is not None
        assert dogs.first.age == 10
        assert dogs.first.name == 'Johnny'

    def test_pagination(self):
        """ Test the pagination of the filter results"""
        dogs = drf.DogSchema.filter(per_page=2, order_by=['id'])
        assert dogs is not None
        assert dogs.total == 4
        assert len(dogs.items) == 2
        assert dogs.first.id == 1
        assert dogs.has_next
        assert not dogs.has_prev

        dogs = drf.DogSchema.filter(page=2, per_page=2, order_by=['id'])
        assert len(dogs.items) == 2
        assert dogs.first.id == 3
        assert not dogs.has_next
        assert dogs.has_prev

    def test_delete(self):
        """ Delete an object in the reposoitory by ID"""
        del_count = drf.DogSchema.delete(1)
        assert del_count == 1

        del_count = drf.DogSchema.delete(1)
        assert del_count == 0

        with pytest.raises(ObjectNotFoundError):
            drf.DogSchema.get(1)
