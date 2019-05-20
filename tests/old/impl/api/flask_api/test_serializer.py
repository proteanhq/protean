"""Module to test Serializer functionality"""

# Protean
import marshmallow as ma
import pytest

from protean import Domain
from protean.core.exceptions import ConfigurationError
from protean.impl.api.flask.serializers import EntitySerializer
from tests.old.support.dog import Dog, HasManyDog1
from tests.old.support.human import HasManyHuman1
from tests.old.support.sample_flask_app.serializers import HasManyDog1Serializer, HasManyHuman1DetailSerializer


class DogSerializer(EntitySerializer):
    """ Serializer for the Dog Entity """
    class Meta:
        entity = Dog


class TestEntitySerializer:
    """Tests for EntitySerializer class"""

    def test_init(self):
        """Test initialization of EntitySerializer derived class"""
        s = DogSerializer()
        assert s is not None

        # Check that the entity gets serialized correctly
        s_result = s.dump(Dog(id=1, name='Johnny', owner='John'))
        expected_data = {'age': 5, 'id': 1, 'name': 'Johnny', 'owner': 'John'}
        assert s_result.data == expected_data

    def test_abstraction(self):
        """Test that EntitySerializer class itself cannot be initialized"""

        with pytest.raises(ConfigurationError):
            EntitySerializer()

    def test_include_fields(self):
        """ Test the include fields option of the serializer"""

        class DogSerializer2(EntitySerializer):
            """ Serializer for the Dog Entity """
            class Meta:
                entity = Dog
                fields = ('id', 'age')

        s = DogSerializer2()
        assert s is not None

        # Check that the entity gets serialized correctly
        s_result = s.dump(Dog(id=1, name='Johnny', owner='John'))
        expected_data = {'age': 5, 'id': 1}
        assert s_result.data == expected_data

    def test_exclude_fields(self):
        """ Test the exclude fields option of the serializer"""

        class DogSerializer2(EntitySerializer):
            """ Serializer for the Dog Entity """
            class Meta:
                entity = Dog
                exclude = ('id', 'age')

        s = DogSerializer2()
        assert s is not None

        # Check that the entity gets serialized correctly
        s_result = s.dump(Dog(id=1, name='Johnny', owner='John'))
        expected_data = {'name': 'Johnny', 'owner': 'John'}
        assert s_result.data == expected_data

    def test_method_fields(self):
        """ Test the method field type of the serializer"""

        class DogSerializer2(EntitySerializer):
            """ Serializer for the Dog Entity """
            old = ma.fields.Method('get_old')

            def get_old(self, obj):
                """ Check if the dog is old or young """
                if obj.age > 5:
                    return True
                else:
                    return False

            class Meta:
                entity = Dog

        s = DogSerializer2()
        assert s is not None

        # Check that the entity gets serialized correctly
        s_result = s.dump(Dog(id=1, name='Johnny', owner='John'))
        expected_data = {
            'name': 'Johnny',
            'owner': 'John',
            'age': 5,
            'id': 1,
            'old': False
        }
        assert s_result.data == expected_data


class TestEntitySerializer2:
    """Tests for EntitySerializer class with related fields """

    @classmethod
    def setup_class(cls):
        """ Setup the test case """
        cls.human = Domain().get_repository(HasManyHuman1).create(
            id=1, first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')

    def test_reference_field(self, test_domain):
        """ Test that the reference field gets serialized """

        dog = test_domain.get_repository(HasManyDog1).create(id=5, name='Johnny', has_many_human1=self.human)

        # Check that the entity gets serialized correctly
        s = HasManyDog1Serializer()
        s_result = s.dump(dog)
        expected_data = {
            'name': 'Johnny',
            'has_many_human1':  {
                'first_name': 'Jeff', 'id': 1,
                'last_name': 'Kennedy', 'email': 'jeff.kennedy@presidents.com'},
            'age': 5,
            'id': 5,
        }
        assert s_result.data == expected_data

    def test_hasmany_association(self, test_domain):
        """ Test the has many association gets serialized """
        test_domain.get_repository(HasManyDog1).create(id=5, name='Johnny', has_many_human1=self.human)

        s = HasManyHuman1DetailSerializer()
        self.human.dogs
        s_result = s.dump(self.human)
        expected_data = {
            'dogs': [{'age': 5, 'id': 5, 'name': 'Johnny'}],
            'first_name': 'Jeff',
            'last_name': 'Kennedy',
            'email': 'jeff.kennedy@presidents.com',
            'id': 1
        }
        assert s_result.data == expected_data
