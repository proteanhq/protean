"""Human Support Class for Test Cases"""

from protean.core import field
from protean.core.field import association
from protean.core.entity import Entity
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
    dog = association.HasOne('HasOneDog1')


class HasOneHuman1Model(DictModel):
    """ Model for the HasOneHuman1 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasOneHuman1
        model_name = 'has_one_humans1'


class HasOneHuman2(Entity):
    """This is a dummy Human Entity class to test HasOne association"""
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dog = association.HasOne('HasOneDog2', via='human_id')


class HasOneHuman2Model(DictModel):
    """ Model for the HasOneHuman2 Entity"""

    class Meta:
        """ Meta class for model options"""
        entity = HasOneHuman2
        model_name = 'has_one_humans1'