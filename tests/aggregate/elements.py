from datetime import datetime

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import Auto, DateTime, String


class Role(BaseAggregate):
    name = String(max_length=15, required=True)
    created_on = DateTime(default=datetime.today())


# Aggregates to test Identity
class PersonAutoSSN(BaseAggregate):
    ssn = Auto(identifier=True)
    name = String(max_length=25)


class PersonExplicitID(BaseAggregate):
    ssn = String(max_length=36, identifier=True)
    name = String(max_length=25)


# Aggregates to test Subclassing
class SubclassRole(Role):
    pass


# Aggregates to test Abstraction # START #
class AbstractRole(BaseAggregate):
    foo = String(max_length=25)

    class Meta:
        abstract = True


class ConcreteRole(AbstractRole):
    bar = String(max_length=25)


class FurtherAbstractRole(ConcreteRole):
    foobar = String(max_length=25)

    class Meta:
        abstract = True
# Aggregates to test Abstraction # END #


# Aggregates to test Meta Info overriding # START #
class DbRole(BaseAggregate):
    bar = String(max_length=25)

    class Meta:
        schema_name = 'foosball'


class SqlRole(Role):

    class Meta:
        schema_name = 'roles'


class DifferentDbRole(Role):

    class Meta:
        provider = 'non-default'


class SqlDifferentDbRole(Role):

    class Meta:
        provider = 'non-default-sql'


class OrderedRole(BaseAggregate):
    bar = String(max_length=25)

    class Meta:
        order_by = 'bar'


class OrderedRoleSubclass(Role):
    bar = String(max_length=25)

    class Meta:
        order_by = 'bar'
# Aggregates to test Meta Info overriding # END #
