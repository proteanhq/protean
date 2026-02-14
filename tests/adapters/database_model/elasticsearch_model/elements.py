import re
from datetime import datetime
from typing import ClassVar

from elasticsearch_dsl import Keyword, Text

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.core.entity import invariant
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import ValueObject


class Person(BaseAggregate):
    first_name: str
    last_name: str
    age: int = 21
    created_at: datetime | None = datetime.now()


class Alien(BaseAggregate):
    first_name: str
    last_name: str
    age: int = 21


class User(BaseAggregate):
    email: str
    password: str | None = None


class Email(BaseValueObject):
    REGEXP: ClassVar[str] = r"\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?"

    # This is the external facing data attribute
    address: str

    @invariant.post
    def validate_email_address(self):
        """Business rules of Email address"""
        if not bool(re.match(Email.REGEXP, self.address)):
            raise ValidationError({"address": ["email address"]})


class ComplexUser(BaseAggregate):
    email = ValueObject(Email, required=True)
    password: str


class Provider(BaseAggregate):
    name: str | None = None
    about: str | None = None


class ProviderCustomModel(BaseDatabaseModel):
    id = Keyword()
    name = Text(fields={"raw": Keyword()})
    about = Text()


class Receiver(BaseAggregate):
    name: str | None = None
    age: int | None = None
