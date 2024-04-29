from protean import Domain
from protean.fields import Identifier, String

domain = Domain(__file__)


@domain.aggregate
class User:
    name = String(max_length=50)


@domain.entity(aggregate_cls=User)
class Credentials:
    email = String(max_length=254)
    password_hash = String(max_length=128)


@domain.event(aggregate_cls=User)
class Registered:
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()
