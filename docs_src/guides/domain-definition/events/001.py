from enum import Enum

from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain(name="Authentication")


class UserStatus(Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


@domain.event(part_of="User")
class UserActivated:
    user_id: str


@domain.event(part_of="User")
class UserRenamed:
    user_id: str
    name: Annotated[str, Field(max_length=50)]


@domain.aggregate
class User:
    name: Annotated[str, Field(max_length=50)]
    email: str
    status: UserStatus | None = None

    def activate(self) -> None:
        self.status = UserStatus.ACTIVE.value
        self.raise_(UserActivated(user_id=self.id))

    def change_name(self, name: str) -> None:
        self.name = name
        self.raise_(UserRenamed(user_id=self.id, name=name))
