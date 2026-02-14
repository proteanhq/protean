import re
from typing import ClassVar, List

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.core.entity import invariant
from protean.core.repository import BaseRepository
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Text, ValueObject
from protean.utils.globals import current_domain


class Person(BaseAggregate):
    first_name: str
    last_name: str
    age: int = 21


class PersonRepository(BaseRepository):
    def find_adults(self, minimum_age: int = 21) -> List[Person]:
        return current_domain.repository_for(Person)._dao.filter(age__gte=minimum_age)


class Email(BaseValueObject):
    REGEXP: ClassVar[str] = r"\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?"

    # This is the external facing data attribute
    address: str

    @invariant.post
    def validate_email_address(self):
        """Business rules of Email address"""
        if not bool(re.match(Email.REGEXP, self.address)):
            raise ValidationError({"address": ["email address"]})


class User(BaseAggregate):
    email = ValueObject(Email, required=True)
    password: str


class Provider(BaseAggregate):
    name: str | None = None
    age: int | None = None


class ProviderCustomModel(BaseDatabaseModel):
    name = Text()


class Receiver(BaseAggregate):
    name: str | None = None
    age: int | None = None
