"""Fixture: ``@domain.upcaster`` keeps the decorated class's type."""

from typing import Any

from protean.core.upcaster import BaseUpcaster
from protean.domain import Domain

domain = Domain(name="Strict")


@domain.upcaster(event_type="ThingCreated", from_version=1, to_version=2)
class UpcastThingV1ToV2(BaseUpcaster):
    def upcast(self, data: dict[str, Any]) -> dict[str, Any]:
        return data


@domain.upcaster
class UpcastThingV2ToV3(BaseUpcaster):
    def upcast(self, data: dict[str, Any]) -> dict[str, Any]:
        return data


reveal_type(UpcastThingV1ToV2())  # R: UpcastThingV1ToV2
reveal_type(UpcastThingV2ToV3().upcast({}))  # R: dict[str, Any]


class UpcastThingV3ToV4(BaseUpcaster):
    def upcast(self, data: dict[str, Any]) -> dict[str, Any]:
        return data


# Registering a class directly, with options, keeps its type too.
registered = domain.upcaster(
    UpcastThingV3ToV4, event_type="ThingCreated", from_version=3, to_version=4
)
reveal_type(registered())  # R: UpcastThingV3ToV4
