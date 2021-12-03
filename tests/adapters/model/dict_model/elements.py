import re

from collections import defaultdict
from typing import List

from protean import BaseAggregate, BaseModel, BaseRepository, BaseValueObject
from protean.fields import Integer, String, Text, ValueObject
from protean.globals import current_domain


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.repository_for(Person)._dao.filter(age__gte=minimum_age)

    class Meta:
        aggregate_cls = Person


class Email(BaseValueObject):
    REGEXP = r"\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?"

    # This is the external facing data attribute
    address = String(max_length=254, required=True)

    def clean(self):
        """Business rules of Email address"""
        errors = defaultdict(list)

        if not bool(re.match(Email.REGEXP, self.address)):
            errors["address"].append("is invalid")

        return errors


class User(BaseAggregate):
    email = ValueObject(Email, required=True)
    password = String(required=True, max_length=255)


class Provider(BaseAggregate):
    name = String()
    age = Integer()


class ProviderCustomModel(BaseModel):
    name = Text()

    class Meta:
        entity_cls = Provider
        schema_name = "adults"


class Receiver(BaseAggregate):
    name = String()
    age = Integer()
