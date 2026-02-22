from protean import Domain
from protean.fields import Identifier, String

domain = Domain()


@domain.aggregate
class User:
    name: String(max_length=50)


@domain.entity(part_of=User)
class Credentials:
    email: String(max_length=254)
    password_hash: String(max_length=128)


@domain.command(part_of=User)
class Register:
    id: Identifier()
    email: String()
    name: String()
    password_hash: String()
