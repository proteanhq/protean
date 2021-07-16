import re

from collections import defaultdict
from datetime import datetime

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import DateTime, Integer, String
from protean.core.field.embedded import ValueObject
from protean.core.repository import BaseRepository
from protean.core.value_object import BaseValueObject


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)
    created_at = DateTime(default=datetime.now())


class PersonRepository(BaseRepository):
    pass


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

    def clean(self):
        """ Business rules of Email address """
        errors = defaultdict(list)

        if not bool(re.match(Email.REGEXP, self.address)):
            errors["address"].append("is invalid")

        return errors


class ComplexUser(BaseAggregate):
    email = ValueObject(Email, required=True)
    password = String(required=True, max_length=255)
