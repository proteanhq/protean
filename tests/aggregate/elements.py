from typing import List
from datetime import datetime

from protean.core.aggregate import BaseAggregate
from protean.core.field.association import HasMany, HasOne, Reference
from protean.core.entity import BaseEntity
from protean.core.field.basic import Auto, DateTime, Integer, String, Text
from protean.core.repository.base import BaseRepository


class Role(BaseAggregate):
    name = String(max_length=15, required=True)
    created_on = DateTime(default=datetime.today())


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonRepository(BaseRepository):
    def find_adults(self, age: int = 21) -> List[Person]:
        pass  # FIXME Implement filter method


# Aggregates to test Identity
class PersonAutoSSN(BaseAggregate):
    ssn = Auto(identifier=True)
    name = String(max_length=25)


class PersonExplicitID(BaseAggregate):
    ssn = String(max_length=36, identifier=True)
    name = String(max_length=25)


# Aggregates to test Subclassing
class SubclassRole(Role):
    pass


# Aggregates to test Abstraction # START #
class AbstractRole(BaseAggregate):
    foo = String(max_length=25)

    class Meta:
        abstract = True


class ConcreteRole(AbstractRole):
    bar = String(max_length=25)


class FurtherAbstractRole(ConcreteRole):
    foobar = String(max_length=25)

    class Meta:
        abstract = True
# Aggregates to test Abstraction # END #


# Aggregates to test Meta Info overriding # START #
class DbRole(BaseAggregate):
    bar = String(max_length=25)

    class Meta:
        schema_name = 'foosball'


class SqlRole(Role):

    class Meta:
        schema_name = 'roles'


class DifferentDbRole(Role):

    class Meta:
        provider = 'non-default'


class SqlDifferentDbRole(Role):

    class Meta:
        provider = 'non-default-sql'


class OrderedRole(BaseAggregate):
    bar = String(max_length=25)

    class Meta:
        order_by = 'bar'


class OrderedRoleSubclass(Role):
    bar = String(max_length=25)

    class Meta:
        order_by = 'bar'
# Aggregates to test Meta Info overriding # END #


# Aggregates to test associations # START #
class Post(BaseAggregate):
    content = Text(required=True)
    comments = HasMany('tests.aggregate.elements.Comment')
    author = Reference('tests.aggregate.elements.Author')


class Author(BaseEntity):
    first_name = String(required=True, max_length=25)
    last_name = String(max_length=25)
    posts = HasMany('tests.aggregate.elements.Post')
    account = Reference('tests.aggregate.elements.Account')


class Account(BaseEntity):
    email = String(required=True, max_length=255, unique=True, identifier=True)
    password = String(required=True, max_length=255)
    username = String(max_length=255, unique=True)
    author = HasOne('tests.aggregate.elements.Author')


class Profile(BaseEntity):
    about_me = Text()
    account = Reference('tests.aggregate.elements.Account', via='username')


class Comment(BaseEntity):
    content = Text()
    added_on = DateTime()
    post = Reference('tests.aggregate.elements.Post')
# Aggregates to test associations # END #
