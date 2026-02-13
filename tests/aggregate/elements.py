from __future__ import annotations

from datetime import datetime
from typing import Annotated, List
from uuid import uuid4

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.repository import BaseRepository
from protean.fields import HasMany, HasOne, Reference


class Role(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=15)]
    created_on: datetime = Field(default_factory=datetime.today)


class RoleClone(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=15)]
    created_on: datetime = Field(default_factory=datetime.today)


class Person(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)]
    age: int = 21


class PersonRepository(BaseRepository):
    def find_adults(self, age: int = 21) -> List[Person]:
        pass  # FIXME Implement filter method


# Aggregates to test Identity
class PersonAutoSSN(BaseAggregate):
    ssn: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    name: Annotated[str, Field(max_length=25)] | None = None


class PersonExplicitID(BaseAggregate):
    ssn: Annotated[
        str,
        Field(max_length=36, json_schema_extra={"identifier": True}),
    ]
    name: Annotated[str, Field(max_length=25)] | None = None


# Aggregates to test Subclassing
class SubclassRole(Role):
    pass


# Aggregates to test Abstraction # START #
class AbstractRole(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    foo: Annotated[str, Field(max_length=25)] | None = None


class ConcreteRole(AbstractRole):
    bar: Annotated[str, Field(max_length=25)] | None = None


# Aggregates to test Abstraction # END #


# Aggregates to test associations # START #
class Post(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    content: str
    comments = HasMany("tests.aggregate.elements.Comment")
    author = Reference("tests.aggregate.elements.Author")


class Comment(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    content: str | None = None
    added_on: datetime | None = None

    post = Reference("tests.aggregate.elements.Post")


class Account(BaseAggregate):
    email: Annotated[
        str,
        Field(
            max_length=255,
            json_schema_extra={"identifier": True, "unique": True},
        ),
    ]
    password: Annotated[str, Field(max_length=255)]
    username: (
        Annotated[
            str,
            Field(max_length=255, json_schema_extra={"unique": True}),
        ]
        | None
    ) = None
    author = HasOne("tests.aggregate.elements.Author")


class Author(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=25)]
    last_name: Annotated[str, Field(max_length=25)] | None = None
    account = Reference("tests.aggregate.elements.Account")


class Profile(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    about_me: str | None = None
    account = Reference("tests.aggregate.elements.Account")


class AccountWithId(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    email: Annotated[
        str,
        Field(max_length=255, json_schema_extra={"unique": True}),
    ]
    password: Annotated[str, Field(max_length=255)]
    username: (
        Annotated[
            str,
            Field(max_length=255, json_schema_extra={"unique": True}),
        ]
        | None
    ) = None
    author = HasOne("tests.aggregate.elements.Author")


class ProfileWithAccountId(BaseEntity):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    about_me: str | None = None
    account = Reference("tests.aggregate.elements.AccountWithId")


# Aggregates to test associations # END #
