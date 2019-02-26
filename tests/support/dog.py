"""Support Classes for Test Cases"""

from tests.support.human import Human

from protean.core import field
from protean.core.entity import Entity
from protean.impl.repository.dict_repo import DictModel


class Dog(Entity):
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.String(required=True, max_length=15)


class DogModel(DictModel):
    """ Model for the Dog Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = Dog
        model_name = 'dogs'


class RelatedDog(Entity):
    """This is a dummy Dog Entity class with an association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference(Human)


class RelatedDogModel(DictModel):
    """ Model for the RelatedDog Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = RelatedDog
        model_name = 'related_dogs'


class DogRelatedByEmail(Entity):
    """This is a dummy Dog Entity class with an association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference(Human, via='email')


class DogRelatedByEmailModel(DictModel):
    """ Model for the DogRelatedByEmail Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = DogRelatedByEmail
        model_name = 'related_dogs_by_email'
