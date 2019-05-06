"""Human Support Class for Test Cases"""

from protean import DomainElement
from protean.core import field
from protean.core.entity import Entity
from protean.core.field import association


@DomainElement
class Human(Entity):
    """This is a dummy Human Entity class"""
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)


@DomainElement
class HasOneHuman1(Entity):
    """This is a dummy Human Entity class to test HasOne association"""
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dog = association.HasOne('tests.support.dog.HasOneDog1')


@DomainElement
class HasOneHuman2(Entity):
    """This is a dummy Human Entity class to test HasOne association
       with a custom attribute defined in `via` argument to field
    """
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dog = association.HasOne('tests.support.dog.HasOneDog2', via='human_id')


@DomainElement
class HasOneHuman3(Entity):
    """This is a dummy Human Entity class to test HasOne association
       when there is no corresponding Reference defined in the target class
    """
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dog = association.HasOne('tests.support.dog.HasOneDog3', via='human_id')


@DomainElement
class HasManyHuman1(Entity):
    """This is a dummy Human Entity class to test HasMany association"""
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dogs = association.HasMany('tests.support.dog.HasManyDog1')


@DomainElement
class HasManyHuman2(Entity):
    """This is a dummy Human Entity class to test HasMany association
       with a custom attribute defined in `via` argument to field
    """
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dogs = association.HasMany('HasManyDog2', via='human_id')


@DomainElement
class HasManyHuman3(Entity):
    """This is a dummy Human Entity class to test HasMany association
       when there is no corresponding Reference defined in the target class
    """
    first_name = field.String(required=True, unique=True, max_length=50)
    last_name = field.String(required=True, unique=True, max_length=50)
    email = field.String(required=True, unique=True, max_length=50)
    dogs = association.HasMany('tests.support.dog.HasManyDog3', via='human_id')
