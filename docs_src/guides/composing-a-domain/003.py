from protean import Domain
from protean.fields import Integer, String

domain = Domain(__file__)


@domain.aggregate
class User:
    first_name = String(max_length=50)
    last_name = String(max_length=50)
    age = Integer()


@domain.entity(aggregate_cls=User)
class Credentials:
    email = String(max_length=254)
    password_hash = String(max_length=128)
