from datetime import datetime
from typing import List

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.repository import BaseRepository
from protean.fields import (
    Auto,
    DateTime,
    HasMany,
    HasOne,
    Integer,
    Reference,
    String,
    Text,
)


class Role(BaseAggregate):
    name = String(max_length=15, required=True)
    created_on = DateTime(default=datetime.today())


class RoleClone(BaseAggregate):
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


class ConcreteRole(AbstractRole):
    bar = String(max_length=25)


# Aggregates to test Abstraction # END #


# Aggregates to test associations # START #
class Post(BaseAggregate):
    content = Text(required=True)
    comments = HasMany("tests.aggregate.elements.Comment")
    author = Reference("tests.aggregate.elements.Author")


class Comment(BaseEntity):
    content = Text()
    added_on = DateTime()

    post = Reference("tests.aggregate.elements.Post")


class Account(BaseAggregate):
    email = String(required=True, max_length=255, unique=True, identifier=True)
    password = String(required=True, max_length=255)
    username = String(max_length=255, unique=True)
    author = HasOne("tests.aggregate.elements.Author")


class Author(BaseEntity):
    first_name = String(required=True, max_length=25)
    last_name = String(max_length=25)
    account = Reference("tests.aggregate.elements.Account")


class Profile(BaseEntity):
    about_me = Text()
    account = Reference("tests.aggregate.elements.Account")


class AccountWithId(BaseAggregate):
    email = String(required=True, max_length=255, unique=True)
    password = String(required=True, max_length=255)
    username = String(max_length=255, unique=True)
    author = HasOne("tests.aggregate.elements.Author")


class ProfileWithAccountId(BaseEntity):
    about_me = Text()
    account = Reference("tests.aggregate.elements.AccountWithId")


# Aggregates to test associations # END #
