from protean import Domain
from protean.fields import Identifier, String

domain = Domain(__file__)


@domain.aggregate
class User:
    name = String(max_length=50)


@domain.entity(part_of=User)
class Credentials:
    email = String(max_length=254)
    password_hash = String(max_length=128)


@domain.event(part_of=User)
class Registered:
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


print(domain.registry.elements)
""" Output:
{
    'aggregates': [<class '__main__.User'>],
    'events': [<class '__main__.Registered'>],
    'entities': [<class '__main__.Credentials'>]
}
"""
