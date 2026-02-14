from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class User:
    first_name: Annotated[str, Field(max_length=50)] | None = None
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int | None = None


@domain.entity(part_of=User)
class Credentials:
    email: Annotated[str, Field(max_length=254)] | None = None
    password_hash: Annotated[str, Field(max_length=128)] | None = None
