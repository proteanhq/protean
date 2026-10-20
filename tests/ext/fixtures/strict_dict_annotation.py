"""Fixture: ``dict[...]`` in the class body of every decorated element kind.

The base class methods are visible on instances, but a bare name in the class
body does not resolve to them, so pydantic's ``BaseModel.dict`` does not
shadow the builtin.
"""

from typing import Any

from protean.domain import Domain
from protean.fields import Dict, Identifier

domain = Domain(name="Strict")


@domain.value_object
class Snapshot:
    data: dict[str, Any] = Dict()


@domain.entity(part_of="Thing")
class Part:
    data: dict[str, Any] = Dict()


@domain.aggregate
class Thing:
    data: dict[str, Any] = Dict()


@domain.command(part_of=Thing)
class ChangeThing:
    thing_id: str = Identifier(required=True)
    changes: dict[str, Any] = Dict()


@domain.event(part_of=Thing)
class ThingChanged:
    thing_id: str = Identifier(required=True)
    changes: dict[str, Any] = Dict()


@domain.projection
class ThingView:
    thing_id: str = Identifier(identifier=True)
    data: dict[str, Any] = Dict()


@domain.query(part_of=ThingView)
class FindThings:
    filters: dict[str, Any] = Dict()


thing = Thing(data={"a": 1})
event = ThingChanged(thing_id="t1", changes={"a": 1})
reveal_type(thing.data)  # R: dict[str, Any]
reveal_type(event.changes)  # R: dict[str, Any]
reveal_type(Snapshot(data={}).data)  # R: dict[str, Any]
reveal_type(Part(data={}).data)  # R: dict[str, Any]
reveal_type(ChangeThing(thing_id="t1").changes)  # R: dict[str, Any]
reveal_type(ThingView(thing_id="t1").data)  # R: dict[str, Any]
reveal_type(FindThings(filters={}).filters)  # R: dict[str, Any]

# Inherited methods stay visible on instances.
reveal_type(event.to_dict())  # R: dict[str, Any]
thing.raise_(event)
