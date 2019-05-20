"""Module to test View functionality and features"""

# Standard Library Imports
import json

# Protean
import pytest

from protean.core.exceptions import ObjectNotFoundError
from tests.old.support.dog import Dog
from tests.old.support.sample_flask_app import app


class TestGenericAPIResource:
    """Class to test Generic API Resource functionality and methods"""

    @pytest.fixture(scope="function")
    def client(self):
        """ Setup client for test cases """
        yield app.test_client()

    def test_show(self, client, test_domain):
        """ Test retrieving an entity using ShowAPIResource"""

        # Create a dog object
        test_domain.get_repository(Dog).create(id=5, name='Johnny', owner='John')

        # Fetch this dog by ID
        rv = client.get('/dogs/5')
        assert rv.status_code == 200

        expected_resp = {
            'dog': {'age': 5, 'id': 5, 'name': 'Johnny', 'owner': 'John'}
        }
        assert rv.json == expected_resp

        # Test search by invalid id
        rv = client.get('/dogs/6')
        assert rv.status_code == 404

        # Delete the dog now
        dog = test_domain.get_repository(Dog).get(5)
        test_domain.get_repository(Dog).delete(dog)

    def test_list(self, client, test_domain):
        """ Test listing an entity using ListAPIResource """
        # Create a dog objects
        test_domain.get_repository(Dog).create(id=1, name='Johnny', owner='John')
        test_domain.get_repository(Dog).create(id=2, name='Mary', owner='John', age=3)
        test_domain.get_repository(Dog).create(id=3, name='Grady', owner='Jane', age=8)
        test_domain.get_repository(Dog).create(id=4, name='Brawny', owner='John', age=2)

        # Get the list of dogs
        rv = client.get('/dogs?order_by[]=age')
        assert rv.status_code == 200
        assert rv.json['total'] == 4
        assert rv.json['dogs'][0] == {'age': 2, 'id': 4, 'name': 'Brawny', 'owner': 'John'}

        # Test with filters
        rv = client.get('/dogs?owner=Jane')
        assert rv.status_code == 200
        assert rv.json['total'] == 1

    def test_create(self, client, test_domain):
        """ Test creating an entity using CreateAPIResource """

        # Create a dog object
        rv = client.post('/dogs',
                         data=json.dumps({
                             'data': {
                                 'id': 5,
                                 'name': 'Johnny',
                                 'owner': 'John'
                             }
                         }),
                         content_type='application/json')
        assert rv.status_code == 201

        expected_resp = {
            'dog': {'age': 5, 'id': 5, 'name': 'Johnny', 'owner': 'John'}
        }
        assert rv.json == expected_resp

        # Test value has been added to db
        dog = test_domain.get_repository(Dog).get(5)
        assert dog is not None
        assert dog.id == 5

        # Delete the dog now
        dog = test_domain.get_repository(Dog).get(5)
        test_domain.get_repository(Dog).delete(dog)

    def test_update(self, client, test_domain):
        """ Test updating an entity using UpdateAPIResource """

        # Create a dog object
        test_domain.get_repository(Dog).create(id=5, name='Johnny', owner='John')

        # Update the dog object
        rv = client.put('/dogs/5', data=json.dumps(dict(age=3)),
                        content_type='application/json')
        assert rv.status_code == 200

        expected_resp = {
            'dog': {'age': 3, 'id': 5, 'name': 'Johnny', 'owner': 'John'}
        }
        assert rv.json == expected_resp

        # Test value has been updated in the db
        dog = test_domain.get_repository(Dog).get(5)
        assert dog is not None
        assert dog.age == 3

        # Delete the dog now
        dog = test_domain.get_repository(Dog).get(5)
        test_domain.get_repository(Dog).delete(dog)

    def test_delete(self, client, test_domain):
        """ Test deleting an entity using DeleteAPIResource """

        # Create a dog object
        test_domain.get_repository(Dog).create(id=5, name='Johnny', owner='John')

        # Delete the dog object
        rv = client.delete('/dogs/5')
        assert rv.status_code == 204
        assert rv.data == b''

        # Test value has been updated in the db
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).get(5)


def test_flask_view():
    """ Test that non Protean views work as before """
    # Create the test client
    client = app.test_client()

    rv = client.get('/flask-view')
    assert rv.status_code == 200
    assert rv.data == b'View Response'

    rv = client.get('/flask-view/abc')
    assert rv.status_code == 404


def test_exception():
    """ Test handling of exceptions by the app """
