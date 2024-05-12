from collections import defaultdict
from enum import Enum

from protean import BaseAggregate, BaseEntity
from protean.fields import Auto, HasOne, Integer, String


class Account(BaseAggregate):
    account_number = String(max_length=50, required=True)


class AbstractPerson(BaseEntity):
    age = Integer(default=5)

    class Meta:
        abstract = True


class ConcretePerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)

    class Meta:
        aggregate_cls = "Account"


class Person(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        aggregate_cls = "Account"


class PersonAutoSSN(BaseEntity):
    ssn = Auto(identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        aggregate_cls = "Account"


class PersonExplicitID(BaseEntity):
    ssn = String(max_length=36, identifier=True)
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        aggregate_cls = "Account"


class Relative(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)
    relative_of = HasOne(Person)

    class Meta:
        aggregate_cls = "Account"


class Adult(Person):
    pass

    class Meta:
        schema_name = "adults"
        aggregate_cls = "Account"


class NotAPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        aggregate_cls = "Account"


# Entities to test Meta Info overriding # START #
class DbPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        schema_name = "pepes"
        aggregate_cls = "Account"


class SqlPerson(Person):
    class Meta:
        schema_name = "people"
        aggregate_cls = "Account"


class DifferentDbPerson(Person):
    class Meta:
        provider = "non-default"
        aggregate_cls = "Account"


class SqlDifferentDbPerson(Person):
    class Meta:
        provider = "non-default-sql"
        aggregate_cls = "Account"


class OrderedPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        order_by = "first_name"
        aggregate_cls = "Account"


class OrderedPersonSubclass(Person):
    class Meta:
        order_by = "last_name"
        aggregate_cls = "Account"


class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"


class Area(BaseAggregate):
    name = String(max_length=50)


class Building(BaseEntity):
    name = String(max_length=50)
    floors = Integer()
    status = String(choices=BuildingStatus)

    class Meta:
        aggregate_cls = "Area"

    def defaults(self):
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value

    def clean(self):
        errors = defaultdict(list)

        if self.floors >= 4 and self.status != BuildingStatus.DONE.value:
            errors["status"].append("should be DONE")

        return errors
