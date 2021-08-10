from collections import defaultdict
from enum import Enum

from protean.core.entity import BaseEntity
from protean.core.field.association import HasOne
from protean.core.field.basic import Auto, Integer, String


class AbstractPerson(BaseEntity):
    age = Integer(default=5)

    class Meta:
        abstract = True


class ConcretePerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)


class AdultAbstractPerson(ConcretePerson):
    age = Integer(default=21)

    class Meta:
        abstract = True


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

    class Meta:
        schema_name = "adults"


class NotAPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)


# Entities to test Meta Info overriding # START #
class DbPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        schema_name = "pepes"


class SqlPerson(Person):
    class Meta:
        schema_name = "people"


class DifferentDbPerson(Person):
    class Meta:
        provider = "non-default"


class SqlDifferentDbPerson(Person):
    class Meta:
        provider = "non-default-sql"


class OrderedPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        order_by = "first_name"


class OrderedPersonSubclass(Person):
    class Meta:
        order_by = "last_name"


class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"


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

    def clean(self):
        errors = defaultdict(list)

        if self.floors >= 4 and self.status != BuildingStatus.DONE.value:
            errors["status"].append("should be DONE")

        return errors
