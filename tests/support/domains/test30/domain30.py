"""Test domain with a malformed (duplicate) upcaster chain.

Two upcasters target the same event + from_version, so the chain build raises
``ConfigurationError``. ``protean check`` must report this as a structured
error (exit 1), not crash with a traceback (#1109).
"""

from protean import Domain
from protean.core.upcaster import BaseUpcaster
from protean.fields import String

domain = Domain(name="TEST30")


@domain.aggregate(is_event_sourced=True)
class Order:
    name = String(max_length=100)


@domain.event(part_of=Order)
class OrderPlaced:
    name = String()


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastA(BaseUpcaster):
    def upcast(self, data):
        return data


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastB(BaseUpcaster):
    def upcast(self, data):
        return data
