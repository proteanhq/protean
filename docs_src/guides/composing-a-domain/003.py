from protean import Domain
from protean.fields import Integer, String

domain = Domain()


@domain.aggregate
class User:
    first_name = String(max_length=50)
    last_name = String(max_length=50)
    age = Integer()


@domain.entity(part_of=User)
class Credentials:
    email = String(max_length=254)
    password_hash = String(max_length=128)
