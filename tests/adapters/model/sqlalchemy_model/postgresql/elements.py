import re

from datetime import datetime

from sqlalchemy import Column, Text

from protean import BaseAggregate, BaseModel, BaseValueObject, invariant
from protean.exceptions import ValidationError
from protean.fields import DateTime, Integer, List, String, ValueObject


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)
    created_at = DateTime(default=datetime.now())


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
    name = String()
    age = Integer()


class ProviderCustomModel(BaseModel):
    name = Column(Text)


class Receiver(BaseAggregate):
    name = String()
    age = Integer()


class ListUser(BaseAggregate):
    email = String(max_length=255, required=True, unique=True)
    roles = List()  # Defaulted to String Content Type


class IntegerListUser(BaseAggregate):
    email = String(max_length=255, required=True, unique=True)
    roles = List(content_type=Integer)
