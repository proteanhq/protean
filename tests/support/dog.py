"""Support Classes for Test Cases"""

from tests.support.human import HasManyHuman1
from tests.support.human import HasManyHuman2
from tests.support.human import HasOneHuman1
from tests.support.human import HasOneHuman2
from tests.support.human import Human

from protean.core import field
from protean.core.entity import Entity


class Dog(Entity):
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.String(required=True, max_length=15)


class RelatedDog(Entity):
    """This is a dummy Dog Entity class with an association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference(Human)


class RelatedDog2(Entity):
    """This is a dummy RelatedDog2 Entity class with reference definition
       containing the target class name as string
    """
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference('tests.support.human.Human')


class DogRelatedByEmail(Entity):
    """This is a dummy Dog Entity class with an association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference(Human, via='email')


class HasOneDog1(Entity):
    """This is a dummy Dog Entity class to test HasOne Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    has_one_human1 = field.Reference(HasOneHuman1)


class HasOneDog2(Entity):
    """This is a dummy Dog Entity class to test HasOne Association, where the associated
       has defined a `via` attribute to finetune linkage
    """
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human = field.Reference(HasOneHuman2)


class HasOneDog3(Entity):
    """This is a dummy Dog Entity class to test HasOne Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human_id = field.Integer()


class HasManyDog1(Entity):
    """This is a dummy Dog Entity class to test HasMany Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    has_many_human1 = field.Reference(HasManyHuman1)


class HasManyDog2(Entity):
    """This is a dummy Dog Entity class to test HasMany Association, where the associated
       has defined a `via` attribute to finetune linkage
    """
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human = field.Reference(HasManyHuman2)


class HasManyDog3(Entity):
    """This is a dummy Dog Entity class to test HasMany Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human_id = field.Integer()


class ThreadedDog(Entity):
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, max_length=50)
    created_by = field.String(required=True, max_length=15)
