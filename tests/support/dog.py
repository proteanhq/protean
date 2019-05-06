"""Support Entity classes for Test Cases"""

from tests.support.human import HasManyHuman1
from tests.support.human import HasManyHuman2
from tests.support.human import HasOneHuman1
from tests.support.human import HasOneHuman2
from tests.support.human import Human

from protean import Entity
from protean.core import field


@Entity
class Dog:
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.String(required=True, max_length=15)


@Entity
class RelatedDog:
    """This is a dummy Dog Entity class with an association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference(Human)


@Entity
class RelatedDog2:
    """This is a dummy RelatedDog2 Entity class with reference definition
       containing the target class name as string
    """
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference('tests.support.human.Human')


@Entity
class DogRelatedByEmail:
    """This is a dummy Dog Entity class with an association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.Reference(Human, via='email')


@Entity
class HasOneDog1:
    """This is a dummy Dog Entity class to test HasOne Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    has_one_human1 = field.Reference(HasOneHuman1)


@Entity
class HasOneDog2:
    """This is a dummy Dog Entity class to test HasOne Association, where the associated
       has defined a `via` attribute to finetune linkage
    """
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human = field.Reference(HasOneHuman2)


@Entity
class HasOneDog3:
    """This is a dummy Dog Entity class to test HasOne Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human_id = field.Integer()


@Entity
class HasManyDog1:
    """This is a dummy Dog Entity class to test HasMany Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    has_many_human1 = field.Reference(HasManyHuman1)


@Entity
class HasManyDog2:
    """This is a dummy Dog Entity class to test HasMany Association, where the associated
       has defined a `via` attribute to finetune linkage
    """
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human = field.Reference(HasManyHuman2)


@Entity
class HasManyDog3:
    """This is a dummy Dog Entity class to test HasMany Association"""
    name = field.String(required=True, unique=True, max_length=50)
    age = field.Integer(default=5)
    human_id = field.Integer()


@Entity
class ThreadedDog:
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, max_length=50)
    created_by = field.String(required=True, max_length=15)


@Entity
class SubDog(Dog):
    """Subclassed Dog Entity class"""
    pass
