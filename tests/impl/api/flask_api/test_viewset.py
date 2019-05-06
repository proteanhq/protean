"""Module to test Viewset functionality and features"""
# Standard Library Imports
import json

# Protean
import pytest

from tests.support.dog import Dog
from tests.support.human import Human
from tests.support.sample_flask_app import app


class TestGenericAPIResourceSet:
    """Class to test GenericAPIResourceSet functionality and methods"""

    @pytest.fixture(scope="function")
    def client(self):
        """ Setup client for test cases """
        yield app.test_client()

    def test_set_show(self, client):
        """ Test retrieving an entity using the resource set"""
        # Create a human object
        Human.create(id=1, first_name='John', last_name='Doe', email='john.doe@gmail.com')

        # Fetch this human by ID
        rv = client.get('/humans/1')
        assert rv.status_code == 200
        expected_resp = {
            'human': {'first_name': 'John', 'id': 1, 'last_name': 'Doe', 'email': 'john.doe@gmail.com'}
        }
        assert rv.json == expected_resp

        # Delete the human now
        human = Human.get(1)
        human.delete()

    def test_set_list(self, client):
        """ Test listing an entity using the resource set"""
        # Create Human objects
        Human.create(id=2, first_name='Jane', last_name='DoeJ', email='jane.doe@gmail.com')
        Human.create(id=3, first_name='Mary', last_name='DoeM', email='mary.doe@gmail.com')

        # Get the list of humans
        rv = client.get('/humans?order_by[]=id')
        assert rv.status_code == 200
        assert rv.json['total'] == 2
        assert rv.json['humans'][0] == {
            'id': 2, 'first_name': 'Jane',
            'last_name': 'DoeJ', 'email': 'jane.doe@gmail.com'
        }

        human = Human.get(2)
        human.delete()
        human = Human.get(3)
        human.delete()

    def test_set_create(self, client):
        """ Test creating an entity using the resource set """

        # Create a human object
        rv = client.post(
            '/humans',
            data=json.dumps(
                {
                    'data': {
                        'id': 1,
                        'first_name': 'Crazy',
                        'last_name': 'John',
                        'email': 'crazyjohn@gmail.com'
                    }
                }),
            content_type='application/json'
        )
        assert rv.status_code == 201

        expected_resp = {
            'human': {
                'id': 1, 'first_name': 'Crazy',
                'last_name': 'John', 'email': 'crazyjohn@gmail.com'}
        }
        assert rv.json == expected_resp

        # Delete the human now
        human = Human.get(1)
        human.delete()

    def test_set_update(self, client):
        """ Test updating an entity using the resource set """

        # Create a human object
        Human.create(id=2, first_name='Jane', last_name='DoeJ', email='jane.doe@gmail.com')

        # Update the human object
        rv = client.put(
            '/humans/2',
            data=json.dumps(
                {'email': 'jane.doer@gmail.com'}
            ),
            content_type='application/json'
        )
        assert rv.status_code == 200

        expected_resp = {
            'human': {
                'id': 2, 'first_name': 'Jane',
                'last_name': 'DoeJ', 'email': 'jane.doer@gmail.com'}
        }
        assert rv.json == expected_resp

        # Delete the human now
        human = Human.get(2)
        human.delete()

    def test_set_delete(self, client):
        """ Test deleting an entity using the resource set """

        # Create a human object
        Human.create(id=1, first_name='John', last_name='Doe', email='john.doe@gmail.com')

        # Delete the dog object
        rv = client.delete('/humans/1')
        assert rv.status_code == 204
        assert rv.data == b''

    def test_custom_route(self, client):
        """ Test custom routes using the resource set """

        # Create a human object
        Human.create(id=1, first_name='John', last_name='Doe', email='john.doe@gmail.com')
        Dog.create(id=1, name='Johnny', owner='John Doe')
        Dog.create(id=2, name='Mary', owner='John Doe', age=3)
        Dog.create(id=3, name='Grady', owner='Jane Doe', age=8)

        # Get the custom route
        rv = client.get('/humans/1/my_dogs')
        assert rv.status_code == 200
        assert rv.json['total'] == 2
        assert rv.json['dogs'][0] == {'age': 3, 'id': 2, 'name': 'Mary',
                                      'owner': 'John Doe'}
