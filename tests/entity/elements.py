# Protean
from protean.core.entity import BaseEntity
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


class Adult(Person):
    pass

    class Meta:
        schema_name = 'adults'


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
        schema_name = 'pepes'


class SqlPerson(Person):

    class Meta:
        schema_name = 'people'


class DifferentDbPerson(Person):

    class Meta:
        provider = 'non-default'


class SqlDifferentDbPerson(Person):

    class Meta:
        provider = 'non-default-sql'


class OrderedPerson(BaseEntity):
    first_name = String(max_length=50, required=True)
    last_name = String(max_length=50)
    age = Integer(default=21)

    class Meta:
        order_by = 'first_name'


class OrderedPersonSubclass(Person):
    class Meta:
        order_by = 'last_name'
