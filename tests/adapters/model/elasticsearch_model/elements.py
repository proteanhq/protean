import re

from datetime import datetime

from elasticsearch_dsl import Keyword, Text

from protean import BaseAggregate, BaseValueObject, invariant
from protean.core.model import BaseModel
from protean.exceptions import ValidationError
from protean.fields import DateTime, Integer, String
from protean.fields import Text as ProteanText
from protean.fields import ValueObject


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)
    created_at = DateTime(default=datetime.now())


class Alien(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class User(BaseAggregate):
    email = String(max_length=255, required=True, unique=True)
    password = String(max_length=3026)


class Email(BaseValueObject):
    REGEXP = r"\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?"

    # This is the external facing data attribute
    address = String(max_length=254, required=True)

    @invariant.post
    def validate_email_address(self):
        """Business rules of Email address"""
        if not bool(re.match(Email.REGEXP, self.address)):
            raise ValidationError({"address": ["email address"]})


class ComplexUser(BaseAggregate):
    email = ValueObject(Email, required=True)
    password = String(required=True, max_length=255)


class Provider(BaseAggregate):
    name = ProteanText()
    about = ProteanText()


class ProviderCustomModel(BaseModel):
    id = Keyword()
    name = Text(fields={"raw": Keyword()})
    about = Text()


class Receiver(BaseAggregate):
    name = String()
    age = Integer()
