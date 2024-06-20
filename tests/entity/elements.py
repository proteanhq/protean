from enum import Enum

from protean import BaseAggregate, BaseEntity, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, HasOne, Integer, String


class Account(BaseAggregate):
    account_number = String(max_length=50, required=True)


class AbstractPerson(BaseAggregate):
    age = Integer(default=5)


class ConcretePerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)


class Person(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class PersonAutoSSN(BaseEntity):
    ssn = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class PersonExplicitID(BaseEntity):
    ssn = String(max_length=36, identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class Relative(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)
    relative_of = HasOne(Person)


class Adult(Person):
    pass


class NotAPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


# Entities to test Meta Info overriding # START #
class DbPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class SqlPerson(Person):
    pass


class OrderedPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


class OrderedPersonSubclass(Person):
    pass


class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"


class Area(BaseAggregate):
    name = String(max_length=50)


class Building(BaseEntity):
    name = String(max_length=50)
    floors = Integer()
    status = String(choices=BuildingStatus)

    def defaults(self):
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value

    @invariant.post
    def test_building_status_to_be_done_if_floors_above_4(self):
        if self.floors >= 4 and self.status != BuildingStatus.DONE.value:
            raise ValidationError(
                {"_entity": ["Building status should be DONE if floors are above 4"]}
            )
