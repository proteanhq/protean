# Standard Library Imports
import re

from collections import defaultdict
from typing import List

# Protean
from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import Integer, String
from protean.core.field.embedded import ValueObjectField
from protean.core.repository.base import BaseRepository
from protean.globals import current_domain
from protean.core.value_object import BaseValueObject


class Person(BaseAggregate):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50, required=True)
    age = Integer(default=21)


class PersonRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.get_dao(Person).filter(age__gte=minimum_age)

    class Meta:
        aggregate_cls = Person


class Email(BaseValueObject):
    REGEXP = r'\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?'

    # This is the external facing data attribute
    address = String(max_length=254, required=True)

    def clean(self):
        """ Business rules of Email address """
        errors = defaultdict(list)

        if not bool(re.match(Email.REGEXP, self.address)):
            errors['address'].append('is invalid')

        return errors


class User(BaseAggregate):
    email = ValueObjectField(Email, required=True)
    password = String(required=True, max_length=255)
