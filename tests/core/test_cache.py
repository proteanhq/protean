"""Tests for Cache Functionality"""
import time

from tests.support.dog import Dog

from protean.core.cache import cache


class TestCache:
    """This class holds tests for Cache class"""

    def test_init(self):
        """Test successful access to the Cache Wrapper"""
        assert cache.provider is not None

    def test_add(self):
        """ Test adding and retrieving an entry to the cache """
        # Add an entity to the cache
        dog = Dog.create(id=1, name='Johnny', owner='John')
        cache.provider.add(f'dog:{dog.id}', dog.to_dict())

        # Retrieve the entity
        dog_d = cache.provider.get(f'dog:{dog.id}')
        assert dog_d == {'age': 5, 'id': 1, 'name': 'Johnny', 'owner': 'John'}

    def test_set(self):
        """ Test setting an existing key and expiry of keys """
        dog = Dog.create(id=1, name='Johnny', owner='John')

        # Set an entity to the cache
        dog = Dog.get(1)
        cache.provider.set(f'dog:{dog.id}', dog.to_dict(), expiry=1)

        # Retrieve the entity
        dog_d = cache.provider.get(f'dog:{dog.id}')
        assert dog_d == {'age': 5, 'id': 1, 'name': 'Johnny', 'owner': 'John'}

        # Sleep and wait for expiry
        time.sleep(2)
        dog_d = cache.provider.get(f'dog:{dog.id}')
        assert dog_d is None

    def test_touch(self):
        """ Test updating the expiry of key using touch """
        dog = Dog.create(id=1, name='Johnny', owner='John')

        # Set an entity to the cache
        dog = Dog.get(1)
        cache.provider.set(f'dog:{dog.id}', dog.to_dict(), expiry=1)

        # Retrieve the entity
        dog_d = cache.provider.get(f'dog:{dog.id}')
        assert dog_d == {'age': 5, 'id': 1, 'name': 'Johnny', 'owner': 'John'}

        # Touch and retrieve the entity again
        cache.provider.touch(f'dog:{dog.id}', expiry=10)
        time.sleep(1)
        dog_d = cache.provider.get(f'dog:{dog.id}')
        assert dog_d is not None

    def test_delete(self):
        """ Test deleting a key from the cache """
        dog = Dog.create(id=1, name='Johnny', owner='John')

        # Set an entity to the cache
        dog = Dog.get(1)
        cache.provider.set(f'dog:{dog.id}', dog.to_dict())

        # Retrieve the entity
        dog_d = cache.provider.get(f'dog:{dog.id}')
        assert dog_d is not None

        # Delete and retrieve again
        dog_d = cache.provider.delete(f'dog:{dog.id}')
        assert dog_d is None

    def test_incr_decr(self):
        """ Test increment and decrement function of the cache"""
        # Create a counter
        cache.provider.set('visitors', 0)
        cache.provider.incr('visitors')
        assert cache.provider.get('visitors') == 1

        # Decrement and check the results
        cache.provider.decr('visitors')
        assert cache.provider.get('visitors') == 0

    def test_set_get_delete_many(self):
        """ Test setting getting and deleting many keys from the cache """
        # Test setting many
        cache.provider.set_many({'k1': 'v1', 'k2': 'v2', 'k3': 'v3'})

        # test getting many
        values = cache.provider.get_many(['k1', 'k2', 'k3'])
        assert values == {'k1': 'v1', 'k2': 'v2', 'k3': 'v3'}

        # Test deleting many
        cache.provider.delete_many(['k1', 'k2', 'k3'])
        values = cache.provider.get_many(['k1', 'k2', 'k3'])
        assert values == {}
