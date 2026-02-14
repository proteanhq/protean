from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class User:
    name: Annotated[str, Field(max_length=50)] | None = None


@domain.entity(part_of=User)
class Credentials:
    email: Annotated[str, Field(max_length=254)] | None = None
    password_hash: Annotated[str, Field(max_length=128)] | None = None


@domain.event(part_of=User)
class Registered:
    id: str | None = None
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


print(domain.registry.elements)
""" Output:
{
    'aggregates': [<class '__main__.User'>],
    'events': [<class '__main__.Registered'>],
    'entities': [<class '__main__.Credentials'>]
}
"""
