""" Serializers used by the sample app """
from protean.impl.api.flask.serializers import EntitySerializer
from protean.impl.api.flask.serializers import ma

from tests.support.dog import Dog
from tests.support.dog import RelatedDog
from tests.support.dog import HasManyDog1
from tests.support.human import Human
from tests.support.human import HasManyHuman1


class DogSerializer(EntitySerializer):
    """ Serializer for Dog Entity"""

    class Meta:
        entity = Dog


class HumanSerializer(EntitySerializer):
    """ Serializer for Human Entity"""

    class Meta:
        entity = Human


class HumanDetailSerializer(EntitySerializer):
    """ Serializer for the Human Entity with association"""
    dogs = ma.fields.Nested('RelatedDogSerializer', many=True,
                            exclude=['owner'])

    class Meta:
        entity = Human


class RelatedDogSerializer(EntitySerializer):
    """ Serializer for the Related Dpg Entity"""
    owner = ma.fields.Nested(HumanSerializer)

    class Meta:
        entity = RelatedDog


class HasManyHuman1Serializer(EntitySerializer):
    """ Serializer for Human Entity"""

    class Meta:
        entity = HasManyHuman1


class HasManyDog1Serializer(EntitySerializer):
    """ Serializer for the Related Dpg Entity"""
    has_many_human1 = ma.fields.Nested(HasManyHuman1Serializer)

    class Meta:
        entity = RelatedDog


class HasManyHuman1DetailSerializer(EntitySerializer):
    """ Serializer for Human Entity"""
    dogs = ma.fields.Nested(HasManyDog1Serializer, many=True,
                            exclude=['has_many_human1'])

    class Meta:
        entity = HasManyHuman1
