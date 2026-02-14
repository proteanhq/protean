from enum import Enum

from protean.utils import DomainObjects


class DummyElement(Enum):
    FOO = "FOO"


class User:
    username: str | None = None
    password: str | None = None


class UserAggregate(User):
    element_type = DomainObjects.AGGREGATE


class UserEntity(User):
    element_type = DomainObjects.ENTITY


class UserVO(User):
    element_type = DomainObjects.VALUE_OBJECT


class UserFoo(User):
    element_type = DummyElement.FOO
