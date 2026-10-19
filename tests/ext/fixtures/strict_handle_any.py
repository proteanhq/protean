"""Fixture: ``@handle`` takes a class, an event type string, or ``"$any"``."""

from typing import Any

from protean.domain import Domain
from protean.fields import Identifier
from protean.utils.mixins import handle

domain = Domain(name="Strict")


@domain.aggregate
class Thing:
    thing_id: str = Identifier(identifier=True)


@domain.event(part_of=Thing)
class ThingCreated:
    thing_id: str = Identifier(required=True)


@domain.command(part_of=Thing)
class CreateThing:
    thing_id: str = Identifier(required=True)


@domain.event_handler(part_of=Thing)
class AuditHandler:
    @handle("$any")
    def on_any(self, event: Any) -> None: ...

    @handle(ThingCreated)
    def on_created(self, event: ThingCreated) -> None: ...

    @handle("Other.ThingFact.v1")
    def on_fact(self, event: Any) -> None: ...


@domain.command_handler(part_of=Thing)
class ThingCommands:
    @handle(CreateThing)
    def create(self, command: CreateThing) -> str:
        return command.thing_id


# The decorated method keeps its message and result types.
reveal_type(AuditHandler.on_created)  # R: def (AuditHandler, ThingCreated)
reveal_type(ThingCommands().create(CreateThing(thing_id="t1")))  # R: str

# The framework calls a handler positionally, so a keyword call is an error.
ThingCommands().create(command=CreateThing(thing_id="t1"))  # E: call-arg

handle(42)  # E: arg-type
