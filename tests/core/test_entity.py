"""Tests for Entity Functionality and Base Classes"""

import pytest

from protean.core.entity import Entity
from protean.core.exceptions import ValidationError
from protean.core import field


class Dog(Entity):
    """This is a dummy Dog Entity class"""
    id = field.Integer(identifier=True)
    name = field.String(required=True, max_length=50, min_length=5)
    age = field.Integer(default=5)
    owner = field.String(required=True, max_length=15)


class TestEntity:
    """This class holds tests for Base Entity Abstract class"""

    def test_init(self):
        """Test successful Account Entity initialization"""

        dog = Dog(
            id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog is not None
        assert dog.name == 'John Doe'
        assert dog.age == 10
        assert dog.owner == 'Jimmy'

    def test_required_fields(self):
        """Test errors if mandatory fields are missing"""

        with pytest.raises(ValidationError):
            Dog(id=2, name='John Doe')

    def test_defaults(self):
        """Test that values are defaulted properly"""
        dog = Dog(
            id=1, name='John Doe', owner='Jimmy')
        assert dog.age == 5

    def test_validate_string_length(self):
        """Test validation of String length checks"""
        with pytest.raises(ValidationError):
            Dog(id=1, name='John Doe',
                owner='12345678901234567890')

    def test_validate_data_value_against_type(self):
        """Test validation of data types of values"""
        with pytest.raises(ValidationError):
            Dog(id=1, name='John Doe',
                owner='1234567890',
                age="foo")

    def test_template_init(self):
        """Test initialization using a template dictionary"""
        with pytest.raises(AssertionError):
            Dog('Dummy')

        dog = Dog(
            dict(id=1, name='John Doe', owner='Jimmy'))
        assert dog.name == 'John Doe'
        assert dog.owner == 'Jimmy'

    def test_error_messages(self):
        """Test the correct error messages are generated"""

        # Test single error message
        try:
            Dog(id=1, name='John Doe')
        except ValidationError as err:
            assert err.normalized_messages == {
                'owner': [Dog.owner.error_messages['required']]}

        # Test multiple error messages
        try:
            Dog(id=1, name='Joh')
        except ValidationError as err:
            assert err.normalized_messages == {
                'name': ['Ensure value has at least 5 characters.'],
                'owner': [Dog.owner.error_messages['required']]}

    def test_entity_inheritance(self):
        """ Test that subclasses of `Entity` can be inherited"""

        class SharedEntity(Entity):
            """ Class that provides the default fields """
            age = field.Integer(default=5)

        class Dog2(SharedEntity):
            """This is a dummy Dog Entity class with a mixin"""
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50, min_length=5)
            owner = field.String(required=True, max_length=15)

        dog2 = Dog2(
            id=3, name='John Doe', owner='Jimmy')
        assert dog2 is not None
        assert dog2.age == 5

    def test_default_id(self):
        """ Test that default id field is assigned when not defined"""

        class Dog2(Entity):
            """This is a dummy Dog Entity class without an id"""
            name = field.String(required=True, max_length=50, min_length=5)

        dog2 = Dog2(
            id=3, name='John Doe')
        assert dog2 is not None
        assert dog2.id == 3

    def test_to_dict(self):
        """Test conversion of the entity to dict"""

        dog = Dog(
            id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog is not None
        assert dog.to_dict() == {
            'age': 10, 'id': 1, 'name': 'John Doe', 'owner': 'Jimmy'}
