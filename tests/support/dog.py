"""Support Classes for Test Cases"""

from tests.support.human import Human, HasOneHuman1, HasOneHuman2

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


class RelatedDog2(Entity):
    """This is a dummy RelatedDog2 Entity class with reference definition
       containing the target class name as string
    """
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference('Human')


class RelatedDog2Model(DictModel):
    """ Model for the RelatedDog2 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = RelatedDog2
        model_name = 'related_dogs2'


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


class HasOneDog1(Entity):
    """This is a dummy Dog Entity class to test HasOne Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    has_one_human1 = field.Reference(HasOneHuman1)


class HasOneDog1Model(DictModel):
    """ Model for the HasOneDog1 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasOneDog1
        model_name = 'has_one_dogs1'


class HasOneDog2(Entity):
    """This is a dummy Dog Entity class to test HasOne Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human = field.Reference(HasOneHuman2)


class HasOneDog2Model(DictModel):
    """ Model for the HasOneDog2 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasOneDog2
        model_name = 'has_one_dogs2'


class HasOneDog3(Entity):
    """This is a dummy Dog Entity class to test HasOne Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human_id = field.Integer()


class HasOneDog3Model(DictModel):
    """ Model for the HasOneDog3 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasOneDog3
        model_name = 'has_one_dogs3'
