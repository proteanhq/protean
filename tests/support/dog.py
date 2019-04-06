"""Support Classes for Test Cases"""

from tests.support.human import HasManyHuman1
from tests.support.human import HasManyHuman2
from tests.support.human import HasOneHuman1
from tests.support.human import HasOneHuman2
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


class RelatedDog2(Entity):
    """This is a dummy RelatedDog2 Entity class with reference definition
       containing the target class name as string
    """
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference('tests.support.human.Human')


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
    """This is a dummy Dog Entity class to test HasOne Association, where the associated
       has defined a `via` attribute to finetune linkage
    """
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


class HasManyDog1(Entity):
    """This is a dummy Dog Entity class to test HasMany Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    has_many_human1 = field.Reference(HasManyHuman1)


class HasManyDog1Model(DictModel):
    """ Model for the HasManyDog1 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasManyDog1
        model_name = 'has_many_dogs1'


class HasManyDog2(Entity):
    """This is a dummy Dog Entity class to test HasMany Association, where the associated
       has defined a `via` attribute to finetune linkage
    """
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human = field.Reference(HasManyHuman2)


class HasManyDog2Model(DictModel):
    """ Model for the HasManyDog2 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasManyDog2
        model_name = 'has_many_dogs2'


class HasManyDog3(Entity):
    """This is a dummy Dog Entity class to test HasMany Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human_id = field.Integer()


class HasManyDog3Model(DictModel):
    """ Model for the HasManyDog3 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasManyDog3
        model_name = 'has_many_dogs3'


class ThreadedDog(Entity):
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, max_length=50)
    created_by = field.String(required=True, max_length=15)


class ThreadedDogModel(DictModel):
    """ Model for the ThreadedDog Entity"""

    class Meta:
        """ Meta class for schema options"""
        entity = ThreadedDog
        model_name = 'threaded_dogs'
