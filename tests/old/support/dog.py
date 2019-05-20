"""Support Entity classes for Test Cases"""

# Protean
from protean import Entity
from protean.core.field.basic import String, Integer, Identifier
from protean.core.field.association import Reference
from tests.old.support.human import HasManyHuman1, HasManyHuman2, HasOneHuman1, HasOneHuman2, Human


@Entity
class Dog:
    """This is a dummy Dog Entity class"""
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    owner = String(required=True, max_length=15)


@Entity
class RelatedDog:
    """This is a dummy Dog Entity class with an association"""
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    owner = Reference(Human)


@Entity
class RelatedDog2:
    """This is a dummy RelatedDog2 Entity class with reference definition
       containing the target class name as string
    """
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    owner = Reference('tests.old.support.human.Human')


@Entity
class DogRelatedByEmail:
    """This is a dummy Dog Entity class with an association"""
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    owner = Reference(Human, via='email')


@Entity
class HasOneDog1:
    """This is a dummy Dog Entity class to test HasOne Association"""
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    has_one_human1 = Reference(HasOneHuman1)


@Entity
class HasOneDog2:
    """This is a dummy Dog Entity class to test HasOne Association, where the associated
       has defined a `via` attribute to finetune linkage
    """
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    human = Reference(HasOneHuman2)


@Entity
class HasOneDog3:
    """This is a dummy Dog Entity class to test HasOne Association"""
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    human_id = Identifier()


@Entity
class HasManyDog1:
    """This is a dummy Dog Entity class to test HasMany Association"""
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    has_many_human1 = Reference(HasManyHuman1)


@Entity
class HasManyDog2:
    """This is a dummy Dog Entity class to test HasMany Association, where the associated
       has defined a `via` attribute to finetune linkage
    """
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    human = Reference(HasManyHuman2)


@Entity
class HasManyDog3:
    """This is a dummy Dog Entity class to test HasMany Association"""
    name = String(required=True, unique=True, max_length=50)
    age = Integer(default=5)
    human_id = Identifier()


@Entity
class ThreadedDog:
    """This is a dummy Dog Entity class"""
    name = String(required=True, max_length=50)
    created_by = String(required=True, max_length=15)


@Entity
class SubDog(Dog):
    """Subclassed Dog Entity class"""
    pass
