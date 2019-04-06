"""Human Support Class for Test Cases"""

from protean.core import field
from protean.core.entity import Entity
from protean.core.field import association
from protean.impl.repository.dict_repo import DictModel


class Human(Entity):
    """This is a dummy Human Entity class"""
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)


class HumanModel(DictModel):
    """ Model for the Human Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = Human
        model_name = 'humans'


class HasOneHuman1(Entity):
    """This is a dummy Human Entity class to test HasOne association"""
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dog = association.HasOne('tests.support.dog.HasOneDog1')


class HasOneHuman1Model(DictModel):
    """ Model for the HasOneHuman1 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasOneHuman1
        model_name = 'has_one_humans1'


class HasOneHuman2(Entity):
    """This is a dummy Human Entity class to test HasOne association
       with a custom attribute defined in `via` argument to field
    """
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dog = association.HasOne('tests.support.dog.HasOneDog2', via='human_id')


class HasOneHuman2Model(DictModel):
    """ Model for the HasOneHuman2 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasOneHuman2
        model_name = 'has_one_humans2'


class HasOneHuman3(Entity):
    """This is a dummy Human Entity class to test HasOne association
       when there is no corresponding Reference defined in the target class
    """
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dog = association.HasOne('tests.support.dog.HasOneDog3', via='human_id')


class HasOneHuman3Model(DictModel):
    """ Model for the HasOneHuman3 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasOneHuman3
        model_name = 'has_one_humans3'


class HasManyHuman1(Entity):
    """This is a dummy Human Entity class to test HasMany association"""
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dogs = association.HasMany('tests.support.dog.HasManyDog1')


class HasManyHuman1Model(DictModel):
    """ Model for the HasManyHuman1 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasManyHuman1
        model_name = 'has_many_humans1'


class HasManyHuman2(Entity):
    """This is a dummy Human Entity class to test HasMany association
       with a custom attribute defined in `via` argument to field
    """
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dogs = association.HasMany('HasManyDog2', via='human_id')


class HasManyHuman2Model(DictModel):
    """ Model for the HasManyHuman2 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasManyHuman2
        model_name = 'has_many_humans2'


class HasManyHuman3(Entity):
    """This is a dummy Human Entity class to test HasMany association
       when there is no corresponding Reference defined in the target class
    """
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dogs = association.HasMany('tests.support.dog.HasManyDog3', via='human_id')


class HasManyHuman3Model(DictModel):
    """ Model for the HasManyHuman3 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasManyHuman3
        model_name = 'has_many_humans3'
