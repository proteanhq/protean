"""Fixture: a decorated element is a subtype of its Protean base class.

The decorator makes the class a subclass of its base at runtime, and the
plugin tells mypy the same. A decorated element is then accepted wherever the
framework's signatures name the base class, ``isinstance`` narrows to it, and
the base's properties bind to it.
"""

from typing import Any

from pydantic import BaseModel

from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.domain import Domain
from protean.fields import Identifier, Integer, String, ValueObject

domain = Domain(name="Strict")


@domain.value_object
class Plain:
    score: int = Integer(required=True)


@domain.aggregate(abstract=True)
class Auditable:
    changed_by: str | None = String()


@domain.aggregate
class Thing:
    name: str | None = String()
    plain: Plain | None = ValueObject(Plain)


# A decorated aggregate that extends a decorated abstract aggregate takes the
# fields of both by keyword.
@domain.aggregate
class Account(Auditable):
    customer_id: str = String(required=True)


@domain.projection
class Leaderboard:
    account_id: str = Identifier(identifier=True)
    points: int | None = Integer()


# The value object factory takes the decorated class.
rating = ValueObject(Plain)
reveal_type(rating)  # R: Plain | None

# A decorated value object is a BaseValueObject.
vo: BaseValueObject = Plain(score=1)

# Cache entry points take a decorated projection, class and instance.
cache = domain.cache_for(Leaderboard)
cache.add(Leaderboard(account_id="a1", points=3))
cache.remove(Leaderboard(account_id="a1"))
domain.projectors_for(Leaderboard)

# Repository and view entry points take decorated classes too.
repository = domain.repository_for(Thing)
repository.add(Thing(name="x"))
view = domain.view_for(Leaderboard)

thing = Thing(name="x")
account = Account(customer_id="c1", changed_by="admin")
reveal_type(account.changed_by)  # R: str | None
Account(customer="c1")  # E: call-arg
reveal_type(thing.state_.is_persisted)  # R: bool


def mark(aggregate: BaseAggregate, anything: Any) -> None:
    # A property of the base binds to a decorated and an abstract aggregate.
    if isinstance(aggregate, Auditable):
        reveal_type(aggregate)  # R: Auditable
        reveal_type(aggregate.state_.is_persisted)  # R: bool
    if isinstance(anything, Auditable):
        reveal_type(anything.state_.is_persisted)  # R: bool


# A decorated class whose own bases leave no consistent order with the
# Protean base still sees the base's methods.
@domain.value_object
class Legacy(BaseModel):
    code: str = String(required=True)


reveal_type(Legacy(code="x").to_dict())  # R: dict[str, Any]
