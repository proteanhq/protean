"""Human Support Class for Test Cases"""

from protean.core import field
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
