"""Test domain with a valid, registered upcaster.

Used to assert upcasters register through the standard element lifecycle and
therefore appear in the IR elements index and in ``protean ir show``.
"""

from protean import Domain
from protean.core.upcaster import BaseUpcaster
from protean.fields import String

domain = Domain(name="TEST29")


@domain.aggregate(is_event_sourced=True)
class Order:
    name = String(max_length=100)


@domain.event(part_of=Order)
class OrderPlaced:
    __version__ = 2
    name = String()


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data):
        return data
