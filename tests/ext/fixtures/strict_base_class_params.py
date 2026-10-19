"""Fixture: a decorated element is a subtype of its Protean base class.

The decorator makes the class a subclass of its base at runtime, and the
plugin tells mypy the same. A decorated element is then accepted wherever the
framework's signatures name the base class, ``isinstance`` narrows to it, and
the base's properties bind to it.
"""

from typing import Any, ClassVar
from typing import ClassVar as CV

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


# A decorated element extending a decorated element with no fields still
# checks its own keywords.
@domain.value_object
class Marker:
    pass


@domain.value_object
class Score(Marker):
    value: int = Integer(required=True)


Score(value=1)
Score(valu=1)  # E: call-arg


# A plain annotation is a pydantic field at runtime, so it is a keyword too.
@domain.command(part_of=Thing)
class Rename:
    name: str
    reason: str | None


reveal_type(Rename(name="new").name)  # R: str
Rename(name="new", reason="typo")
Rename(nam="new")  # E: call-arg


# A hand-written ``__init__`` is kept.
@domain.value_object
class Pair:
    left: int = Integer(required=True)

    def __init__(self, left: int) -> None:
        super().__init__(left=left)


Pair(1)


# A subclass of a hand-written ``__init__`` inherits it at runtime, so its own
# fields are not keywords.
@domain.aggregate
class Handmade:
    def __init__(self, *, left: int = 0) -> None:
        super().__init__()


@domain.aggregate
class HandmadeChild(Handmade):
    right: int | None = Integer()


HandmadeChild(left=1)
HandmadeChild(right=1)  # E: call-arg


# A parent that subclasses its base without a decorator gets an ``__init__``
# from the dataclass transform, and a decorated child adds its own fields.
class Transformed(BaseAggregate):
    left: int | None = Integer()


@domain.aggregate
class TransformedChild(Transformed):
    right: int | None = Integer()


TransformedChild(left=1, right=2)
TransformedChild(rght=2)  # E: call-arg


# A class with two such parents takes the fields of both.
class Other(BaseAggregate):
    other: int | None = Integer()


@domain.aggregate
class Both(Transformed, Other):
    own: int | None = Integer()


Both(left=1, other=2, own=3)
Both(othr=2)  # E: call-arg


# An annotation with a default is a keyword like one without.
@domain.value_object
class Label:
    label: str = "unset"
    size: int = 0


Label(label="x", size=2)
Label(lable="x")  # E: call-arg


# Private names and class variables are not constructor keywords.
@domain.command(part_of=Thing)
class Tag:
    label: str
    _cache: str
    KIND: ClassVar[str]


Tag(label="x")
Tag(_cache="x")  # E: call-arg
Tag(KIND="x")  # E: call-arg


# A class variable imported under another name is still not a keyword.
@domain.command(part_of=Thing)
class Badge:
    label: str
    KIND: CV[str] = "badge"


Badge(label="x")
Badge(KIND="x")  # E: call-arg


# The decorator rebuilds the class on its Protean base alone, so the class's
# own bases are dropped at runtime and for mypy.
class Greeter:
    def hello(self) -> str:
        return "hello"


@domain.aggregate
class Greeted(Greeter):
    name: str | None = String()


@domain.value_object
class Legacy(BaseModel):
    code: str = String(required=True)


Greeted().hello()  # E: attr-defined
reveal_type(Legacy(code="x").to_dict())  # R: dict[str, Any]
