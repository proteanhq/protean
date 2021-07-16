from enum import Enum

from protean.core.field.basic import String
from protean.utils import DomainObjects


class DummyElement(Enum):
    FOO = "FOO"


class User:
    username = String(max_length=50)
    password = String(max_length=255)


class UserAggregate(User):
    element_type = DomainObjects.AGGREGATE


class UserEntity(User):
    element_type = DomainObjects.ENTITY


class UserVO(User):
    element_type = DomainObjects.VALUE_OBJECT


class UserFoo(User):
    element_type = DummyElement.FOO
