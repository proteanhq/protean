from protean.fields import HasOne

from ..publishing20 import publishing


@publishing.aggregate
class Account:
    email: str | None = None
    password: str
    username: str | None = None
    author = HasOne("Author")


@publishing.entity(part_of=Account)
class Author:
    first_name: str
    last_name: str | None = None
