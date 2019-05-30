""" Tests for the entity state class"""
# Protean
from protean.core.exceptions import ValidationError
from tests.old.support.dog import Dog


class TestState:
    """Class that holds tests for Entity State Management"""

    def test_default_state(self):
        """Test that a default state is available when the entity is instantiated"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog.state_ is not None
        assert dog.state_._new
        assert dog.state_.is_new
        assert not dog.state_.is_persisted

    def test_state_on_retrieved_objects(self, test_domain):
        """Test that retrieved objects are not marked as new"""
        dog = test_domain.get_repository(Dog).create(name='John Doe', age=10, owner='Jimmy')
        dog_dup = test_domain.get_repository(Dog).get(dog.id)

        assert not dog_dup.state_.is_new

    def test_persisted_after_save(self, test_domain):
        """Test that the entity is marked as saved after successfull save"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog.state_.is_new
        test_domain.get_repository(Dog).save(dog)
        assert dog.state_.is_persisted

    def test_not_persisted_if_save_failed(self, test_domain):
        """Test that the entity still shows as new if save failed"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        try:
            del dog.name
            test_domain.get_repository(Dog).save(dog)
        except ValidationError:
            assert dog.state_.is_new

    def test_persisted_after_create(self, test_domain):
        """Test that the entity is marked as saved after successfull create"""
        dog = test_domain.get_repository(Dog).create(id=1, name='John Doe', age=10, owner='Jimmy')
        assert not dog.state_.is_new

    def test_copy_resets_state(self, test_domain):
        """Test that a default state is available when the entity is instantiated"""
        dog1 = test_domain.get_repository(Dog).create(id=1, name='John Doe', age=10, owner='Jimmy')
        dog2 = dog1.clone()

        assert dog2.state_.is_new

    def test_changed(self, test_domain):
        """Test that entity is marked as changed if attributes are updated"""
        dog = test_domain.get_repository(Dog).create(id=1, name='John Doe', age=10, owner='Jimmy')
        assert not dog.state_.is_changed
        dog.name = 'Jane Doe'
        assert dog.state_.is_changed

    def test_not_changed_if_still_new(self):
        """Test that entity is not marked as changed upon attribute change
        if its still new"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        assert not dog.state_.is_changed
        dog.name = 'Jane Doe'
        assert not dog.state_.is_changed

    def test_not_changed_after_save(self, test_domain):
        """Test that entity is marked as not changed after save"""
        dog = test_domain.get_repository(Dog).create(id=1, name='John Doe', age=10, owner='Jimmy')
        dog.name = 'Jane Doe'
        assert dog.state_.is_changed
        test_domain.get_repository(Dog).save(dog)
        assert not dog.state_.is_changed

    def test_destroyed(self, test_domain):
        """Test that a entity is marked as destroyed after delete"""
        dog = test_domain.get_repository(Dog).create(id=1, name='John Doe', age=10, owner='Jimmy')
        assert not dog.state_.is_destroyed
        test_domain.get_repository(Dog).delete(dog)
        assert dog.state_.is_destroyed
