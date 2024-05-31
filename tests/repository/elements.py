import re

from typing import List

from protean import BaseAggregate, BaseRepository, BaseValueObject, invariant
from protean.exceptions import ValidationError
from protean.fields import Integer, String, ValueObject
from protean.globals import current_domain


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.repository_for(Person)._dao.filter(age__gte=minimum_age)

    class Meta:
        part_of = Person


class Email(BaseValueObject):
    REGEXP = r"\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?"

    # This is the external facing data attribute
    address = String(max_length=254, required=True)

    @invariant.post
    def validate_email_address(self):
        """Business rules of Email address"""
        if not bool(re.match(Email.REGEXP, self.address)):
            raise ValidationError({"address": ["email address"]})


class User(BaseAggregate):
    email = ValueObject(Email, required=True)
    password = String(required=True, max_length=255)
