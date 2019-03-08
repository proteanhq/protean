""" Tests for the entity state class"""
from tests.support.dog import Dog

from protean.core.exceptions import ValidationError


class TestState:
    """Class that holds tests for Entity State Management"""

    def test_default_state(self):
        """Test that a default state is available when the entity is instantiated"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog._state is not None
        assert dog._state._new
        assert dog._state.is_new()
        assert dog.is_new
        assert not dog.is_persisted

    def test_state_on_retrieved_objects(self):
        """Test that retrieved objects are not marked as new"""
        dog = Dog.create(name='John Doe', age=10, owner='Jimmy')
        dog_dup = Dog.get(dog.id)

        assert not dog_dup.is_new

    def test_persisted_after_save(self):
        """Test that the entity is marked as saved after successfull save"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog.is_new
        dog.save()
        assert dog.is_persisted

    def test_not_persisted_if_save_failed(self):
        """Test that the entity still shows as new if save failed"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        try:
            del dog.name
            dog.save()
        except ValidationError as exc:
            assert dog.is_new

    def test_persisted_after_create(self):
        """Test that the entity is marked as saved after successfull create"""
        dog = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
        assert not dog.is_new

    def test_copy_resets_state(self):
        """Test that a default state is available when the entity is instantiated"""
        dog1 = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
        dog2 = dog1.clone()

        assert dog2.is_new

    def test_changed(self):
        """Test that entity is marked as changed if attributes are updated"""
        dog = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
        assert not dog.is_changed
        dog.name = 'Jane Doe'
        assert dog.is_changed

    def test_not_changed_if_still_new(self):
        """Test that entity is not marked as changed upon attribute change
        if its still new"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        assert not dog.is_changed
        dog.name = 'Jane Doe'
        assert not dog.is_changed

    def test_not_changed_after_save(self):
        """Test that entity is marked as not changed after save"""
        dog = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
        dog.name = 'Jane Doe'
        assert dog.is_changed
        dog.save()
        assert not dog.is_changed

    def test_destroyed(self):
        """Test that a entity is marked as destroyed after delete"""
        dog = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
        assert not dog.is_destroyed
        dog.delete()
        assert dog.is_destroyed
