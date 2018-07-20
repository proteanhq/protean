"""Tests for Entity Functionality and Base Classes"""

import factory
import pytest
from faker import Faker
from pytest_factoryboy import register

from protean.entity import STRING_LENGTHS
from protean.entity import BaseEntity

fake = Faker()  # pylint: disable=C0103


class Dog(BaseEntity):
    """This is a dummy Dog Entity class"""
    _fields = [
        'id', 'name', 'age', 'owner'
    ]
    _field_definitions = {
        'id': {
            'type': 'IDENTIFIER',
            'length': 'IDENTIFIER'
        },
        'name': {
            'type': 'STRING',
            'length': 'MEDIUM'
        },
        'age': {
            'type': 'INTEGER'
        },
        'owner': {
            'type': 'STRING',
            'length': 'SHORT'
        }
    }
    _mandatory = ['name', 'owner']
    _defaults = {
        'age': 5
    }


@register
class DogFactory(factory.Factory):
    """DogFactory"""
    id = fake.uuid4()[:STRING_LENGTHS['IDENTIFIER']]
    name = fake.name()
    owner = fake.name()[:STRING_LENGTHS['SHORT']]

    class Meta:
        """Factory is Connected to Dog"""
        model = Dog


class TestDog:
    """This class holds tests for Base Entity Abstract class"""

    def test_init(self, dog):
        """Test successful Account Entity initialization"""

        dog = Dog(name=dog.name,
                  age=dog.age,
                  owner=dog.owner)

        assert dog is not None

    def test_missing_fields(self, dog):
        """Test errors if mandatory fields are missing"""

        with pytest.raises(ValueError):
            Dog(name=dog.name)

    def test_invalid_fields(self, dog):
        """Test that invalid fields are not set on Dog instance"""

        with pytest.raises(ValueError):
            Dog(name=dog.name,
                age=dog.age,
                foo='bar')

    def test_defaults(self, dog):
        """Test that values are defaulted properly"""
        assert dog.age == 5

    def test_validate_string_length(self, dog):
        """Test validation of String length checks"""
        with pytest.raises(ValueError):
            Dog(id=dog.id,
                name=dog.name,
                owner='12345678901234567890')

    def test_validate_data_value_against_type(self, dog):
        """Test validation of String length checks"""
        with pytest.raises(ValueError):
            Dog(id=dog.id,
                name=dog.name,
                owner='1234567890',
                age="foo")

    def test_validate_data_type(self, dog):
        """Test validation of String length checks"""
        with pytest.raises(TypeError):
            class InvalidDog(BaseEntity):
                """This is a dummy Dog Entity class"""
                _fields = [
                    'name'
                ]
                _field_definitions = {
                    'name': {
                        'type': 'FOO'
                    }
                }
            InvalidDog(name=dog.name)

    def test_sanitization(self, dog):
        """Test that string values are sanitized"""
        dog2 = Dog(id=dog.id,
                   name='an <script>evil()</script> example',
                   owner='1234567890')
        assert getattr(dog2, 'name', None) == u'an &lt;script&gt;evil()&lt;/script&gt; example'
