"""Test domain with a deprecated element (only INFO-level diagnostics).

- DEPRECATED_ELEMENT (info): ``Order`` is marked ``deprecated``
- Has a command handler so AGGREGATE_WITHOUT_COMMAND_HANDLER doesn't fire
- Command is handled so UNUSED_COMMAND doesn't fire

Used by ``tests/cli/test_check.py`` to assert the deprecated-element diagnostic
surfaces end-to-end through ``protean check`` (see #999).
"""

from protean import Domain
from protean.fields import String
from protean.utils.mixins import handle

domain = Domain(name="TEST28")


@domain.aggregate(deprecated={"since": "0.15", "removal": "1.0"})
class Order:
    name = String(max_length=100)


@domain.command(part_of=Order)
class PlaceOrder:
    name = String(required=True)


@domain.command_handler(part_of=Order)
class OrderHandler:
    @handle(PlaceOrder)
    def place(self, command):
        pass
