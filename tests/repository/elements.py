from __future__ import annotations

import re

from typing import Annotated, ClassVar, List
from uuid import uuid4

from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.entity import invariant
from protean.core.repository import BaseRepository
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import ValueObject
from protean.utils.globals import current_domain


class Person(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    first_name: Annotated[str, Field(max_length=50)]
    last_name: Annotated[str, Field(max_length=50)]
    age: int = 21


class PersonRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.repository_for(Person)._dao.filter(age__gte=minimum_age)


class Email(BaseValueObject):
    REGEXP: ClassVar[str] = r"\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?"

    # This is the external facing data attribute
    address: Annotated[str, Field(max_length=254)]

    @invariant.post
    def validate_email_address(self):
        """Business rules of Email address"""
        if not bool(re.match(Email.REGEXP, self.address)):
            raise ValidationError({"address": ["email address"]})


class User(BaseAggregate):
    id: str = Field(
        json_schema_extra={"identifier": True},
        default_factory=lambda: str(uuid4()),
    )
    email = ValueObject(Email, required=True)
    password: Annotated[str, Field(max_length=255)]
