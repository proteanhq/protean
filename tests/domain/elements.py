from enum import Enum

# Protean
from protean.core.field.basic import String
from protean.domain import DomainObjects


class UserStruct:
    element_type = DomainObjects.AGGREGATE

    username = String(max_length=50)
    password = String(max_length=255)


class UserStructVO:
    element_type = DomainObjects.VALUE_OBJECT

    username = String(max_length=50)
    password = String(max_length=255)


class DummyElement(Enum):
    FOO = 'FOO'


class UserStructFoo:
    element_type = DummyElement.FOO

    username = String(max_length=50)
    password = String(max_length=255)
