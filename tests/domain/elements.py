# Standard Library Imports
from enum import Enum

# Protean
from protean.core.field.basic import String
from protean.domain import DomainObjects


class DummyElement(Enum):
    FOO = 'FOO'


class UserStruct:
    username = String(max_length=50)
    password = String(max_length=255)


class UserStructAggregate(UserStruct):
    element_type = DomainObjects.AGGREGATE


class UserStructEntity(UserStruct):
    element_type = DomainObjects.ENTITY


class UserStructVO(UserStruct):
    element_type = DomainObjects.VALUE_OBJECT


class UserStructRequestObject(UserStruct):
    element_type = DomainObjects.REQUEST_OBJECT


class UserStructFoo(UserStruct):
    element_type = DummyElement.FOO
