from protean.fields import HasOne, String

from ..publishing20 import publishing


@publishing.aggregate
class Account:
    email = String(required=True, max_length=255, unique=True, identifier=True)
    password = String(required=True, max_length=255)
    username = String(max_length=255, unique=True)
    author = HasOne("Author")


@publishing.entity
class Author:
    first_name = String(required=True, max_length=25)
    last_name = String(max_length=25)

    class Meta:
        part_of = Account
