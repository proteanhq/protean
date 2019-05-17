"""Human Support Class for Test Cases"""

# Protean
from protean import Entity
from protean.core.field.basic import String
from protean.core.field.association import HasOne, HasMany


@Entity
class Human:
    """This is a dummy Human Entity class"""
    first_name = String(required=True, unique=True, max_length=50)
    last_name = String(required=True, unique=True, max_length=50)
    email = String(required=True, unique=True, max_length=50)


@Entity
class HasOneHuman1:
    """This is a dummy Human Entity class to test HasOne association"""
    first_name = String(required=True, unique=True, max_length=50)
    last_name = String(required=True, unique=True, max_length=50)
    email = String(required=True, unique=True, max_length=50)
    dog = HasOne('tests.support.dog.HasOneDog1')


@Entity
class HasOneHuman2:
    """This is a dummy Human Entity class to test HasOne association
       with a custom attribute defined in `via` argument to field
    """
    first_name = String(required=True, unique=True, max_length=50)
    last_name = String(required=True, unique=True, max_length=50)
    email = String(required=True, unique=True, max_length=50)
    dog = HasOne('tests.support.dog.HasOneDog2', via='human_id')


@Entity
class HasOneHuman3:
    """This is a dummy Human Entity class to test HasOne association
       when there is no corresponding Reference defined in the target class
    """
    first_name = String(required=True, unique=True, max_length=50)
    last_name = String(required=True, unique=True, max_length=50)
    email = String(required=True, unique=True, max_length=50)
    dog = HasOne('tests.support.dog.HasOneDog3', via='human_id')


@Entity
class HasManyHuman1:
    """This is a dummy Human Entity class to test HasMany association"""
    first_name = String(required=True, unique=True, max_length=50)
    last_name = String(required=True, unique=True, max_length=50)
    email = String(required=True, unique=True, max_length=50)
    dogs = HasMany('tests.support.dog.HasManyDog1')


@Entity
class HasManyHuman2:
    """This is a dummy Human Entity class to test HasMany association
       with a custom attribute defined in `via` argument to field
    """
    first_name = String(required=True, unique=True, max_length=50)
    last_name = String(required=True, unique=True, max_length=50)
    email = String(required=True, unique=True, max_length=50)
    dogs = HasMany('HasManyDog2', via='human_id')


@Entity
class HasManyHuman3:
    """This is a dummy Human Entity class to test HasMany association
       when there is no corresponding Reference defined in the target class
    """
    first_name = String(required=True, unique=True, max_length=50)
    last_name = String(required=True, unique=True, max_length=50)
    email = String(required=True, unique=True, max_length=50)
    dogs = HasMany('tests.support.dog.HasManyDog3', via='human_id')
