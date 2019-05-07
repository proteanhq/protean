"""Module to test Repository extended functionality """
# Standard Library Imports
from datetime import datetime

# Protean
from tests.support.sqlalchemy.dog import SqlDog as Dog
from tests.support.sqlalchemy.human import SqlHuman as Human


class TestSqlalchemyRepositoryExt:
    """Class to test Sqlalchemy Repository"""

    def test_create(self):
        """ Test creating an entity with all field types"""

        # Create the entity and validate the results
        human = Human.create(
            name='John Doe', age='30', weight='13.45',
            date_of_birth='01-01-2000',
            hobbies=['swimming'],
            address='Address of the home of John Doe',
            profile={'phone': '90233143112', 'email': 'johndoe@domain.com'})
        assert human is not None
        expected = {
            'id': 1,
            'name': 'John Doe',
            'weight': 13.45,
            'age': 30,
            'is_married': True,
            'hobbies': ['swimming'],
            'profile': {'email': 'johndoe@domain.com', 'phone': '90233143112'},
            'address': 'Address of the home of John Doe',
            'date_of_birth': datetime(2000, 1, 1).date(),
            'created_at': human.created_at

        }
        assert human.to_dict() == expected

        # Check if the object is in the repo
        human = Human.get(1)
        assert human is not None
        assert human.to_dict() == expected

    def test_multiple_dbs(self):
        """ Test repository connections to multiple databases"""
        humans = Human.query.filter().all()
        assert humans is not None

        dogs = Dog.query.filter().all()
        assert dogs is not None
